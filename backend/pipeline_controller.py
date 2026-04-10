"""
Pipeline Controller Service — Final Production-Ready Version
======================================================
Fixes included:
  1. python-dotenv integration for .env file support.
  2. httpx.BasicAuth for reliable Jenkins authentication.
  3. Token stripping to remove hidden whitespace/newlines.
  4. Corrected function signatures for Python 3.12 compatibility.
"""

import os
import ssl
import uuid
import asyncio
import ipaddress
import logging
import contextvars
import re
import base64
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import urlparse, urlunparse
from typing import Annotated, Optional
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl, Field, StringConstraints
from dotenv import load_dotenv

# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================
load_dotenv()
print(f"DEBUG token repr: {repr(os.getenv('JENKINS_TOKEN', ''))}")

# ============================================================
# PYTHON VERSION-SAFE TIMEOUT
# ============================================================
try:
    from asyncio import timeout as async_timeout
except ImportError:
    from async_timeout import timeout as async_timeout


# ============================================================
# CONFIGURATION
# ============================================================
APP_VERSION = "1.0.1"

REDIS_URL                = os.getenv("REDIS_URL",                "redis://localhost:6379")
LOG_ANALYZER_URL         = os.getenv("LOG_ANALYZER_URL",         "http://localhost:5001/api/v1/analyze")
LOG_ANALYZER_HEALTH_URL  = os.getenv("LOG_ANALYZER_HEALTH_URL",  "http://localhost:5001/api/v1/health")
RECOVERY_SERVICE_URL     = os.getenv("RECOVERY_SERVICE_URL",     "http://localhost:8001/recover")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://localhost:7000/notify")
RECOVERY_HEALTH_URL      = os.getenv("RECOVERY_HEALTH_URL",      "http://localhost:8001/health")
NOTIFICATION_HEALTH_URL  = os.getenv("NOTIFICATION_HEALTH_URL",  "http://localhost:7000/health")

# Jenkins Credentials - .strip() ensures no hidden \r or spaces
JENKINS_USER  = os.getenv("JENKINS_USER", "admin")
JENKINS_TOKEN = os.getenv("JENKINS_TOKEN", "").strip().strip("\"'")

HTTP_TIMEOUT         = float(os.getenv("HTTP_TIMEOUT",         "20"))
MAX_RETRIES          = int(os.getenv("MAX_RETRIES",             "3"))
JOB_TIMEOUT          = int(os.getenv("JOB_TIMEOUT",            "120"))
MAX_LOG_SIZE         = int(os.getenv("MAX_LOG_SIZE_MB",         "10")) * 1024 * 1024
JOB_TTL              = int(os.getenv("JOB_TTL",                 "86400"))
HEALTH_CHECK_TIMEOUT = float(os.getenv("HEALTH_CHECK_TIMEOUT", "3"))
RATE_LIMIT           = int(os.getenv("RATE_LIMIT_PER_MINUTE",   "100"))

_ALLOWED_RAW = os.getenv("ALLOWED_LOG_HOSTS", "")
ALLOWED_LOG_HOSTS: set[str] = {
    h.strip().lower() for h in _ALLOWED_RAW.split(",") if h.strip()
}

# ============================================================
# STRUCTURED LOGGING
# ============================================================
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("pipeline-controller")
logger.addFilter(RequestIdFilter())
logging.getLogger("httpx").setLevel(logging.WARNING)

# ============================================================
# DOMAIN EXCEPTIONS
# ============================================================
class UnsafeURLError(ValueError): pass
class LogTooLargeError(ValueError): pass

# ============================================================
# MODELS
# ============================================================
class PipelineStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED  = "FAILED"

class PipelineEvent(BaseModel):
    event_id: Annotated[str, StringConstraints(min_length=10, max_length=100)]
    pipeline_id: Annotated[str, StringConstraints(min_length=3, max_length=100)]
    run_number: int = Field(gt=0)
    status: PipelineStatus
    log_url: HttpUrl

class PipelineResponse(BaseModel):
    job_id: str
    status: str
    submitted_at: str

# ============================================================
# LIFESPAN
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    app.state.redis = redis.from_url(REDIS_URL, decode_responses=True)
    
    if not JENKINS_TOKEN:
        logger.error("!!! JENKINS_TOKEN is missing. Log fetching will fail (401) !!!")
    
    logger.info(f"Pipeline controller v{APP_VERSION} started")
    yield
    await app.state.http.aclose()
    await app.state.redis.close()

app = FastAPI(title="Pipeline Controller", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ============================================================
# UTILITIES
# ============================================================

async def resolve_host(host: str) -> str:
    if host.lower() in ALLOWED_LOG_HOSTS:
        loop = asyncio.get_running_loop()
        results = await loop.getaddrinfo(host, None)
        import socket
        for r in results:
            if r[0] == socket.AF_INET: return r[4][0]
        return results[0][4][0]

    loop = asyncio.get_running_loop()
    results = await loop.getaddrinfo(host, None)
    for r in results:
        raw_ip = r[4][0]
        ip_obj = ipaddress.ip_address(raw_ip)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved:
            raise UnsafeURLError(f"Host {host} resolves to restricted IP {raw_ip}")
    return results[0][4][0]

async def http_request(method: str, url: str, json: Optional[dict] = None) -> httpx.Response:
    client = app.state.http
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.request(method, url, json=json)
            resp.raise_for_status()
            return resp
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                raise
            if attempt == MAX_RETRIES - 1: raise
            await asyncio.sleep(2 ** attempt)

def _build_ssl_context(hostname: str) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx

# ============================================================
# THE FIXED FETCH_LOGS
# ============================================================
async def fetch_logs(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    ip = await resolve_host(hostname)

    # Reconstruct URL for direct IP access
    netloc = f"[{ip}]" if ":" in ip else ip
    if parsed.port: netloc = f"{netloc}:{parsed.port}"
    url_ip = urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))

    # AUTHENTICATION FIX
    auth = None
    if JENKINS_USER and JENKINS_TOKEN:
        logger.info(f"Applying Basic Auth for user: {JENKINS_USER}")
        auth = httpx.BasicAuth(JENKINS_USER, JENKINS_TOKEN)
    
    headers = {"Host": hostname}
    extensions: dict = {"sni_hostname": hostname.encode()}
    if parsed.scheme == "https":
        extensions["ssl_context"] = _build_ssl_context(hostname)

    chunks = []
    total = 0
    async with app.state.http.stream("GET", url_ip, headers=headers, auth=auth, extensions=extensions) as resp:
        if resp.status_code == 401:
            logger.error(f"Unauthorized (401): Jenkins rejected token for {JENKINS_USER}")
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes(65536):
            total += len(chunk)
            if total > MAX_LOG_SIZE: raise LogTooLargeError()
            chunks.append(chunk)

    return b"".join(chunks).decode(errors="ignore")

# ============================================================
# STATE MANAGEMENT
# ============================================================
async def set_job_status(redis_client, job_id: str, status: str, error=None, failure_type=None):
    data = {"status": status}
    if error: data["error"] = error
    if failure_type: data["failure_type"] = failure_type
    async with redis_client.pipeline() as pipe:
        pipe.delete(job_id)
        pipe.hset(job_id, mapping=data)
        pipe.expire(job_id, JOB_TTL)
        await pipe.execute()

async def safe_set_status(redis_client, job_id, status, error=None, failure_type=None):
    try: await set_job_status(redis_client, job_id, status, error, failure_type)
    except Exception: logger.error(f"Redis write failed for {job_id}")

# ============================================================
# PIPELINE LOGIC
# ============================================================
async def _process_pipeline_inner(job_id: str, event: PipelineEvent):
    redis_client = app.state.redis
    logs = await fetch_logs(str(event.log_url))
    
    analysis = await http_request("POST", LOG_ANALYZER_URL, {"log": logs})
    result = analysis.json()
    failure_type = result.get("failure_type")

    if result.get("status") == "FAILED":
        try:
            await http_request("POST", RECOVERY_SERVICE_URL, {
                "pipeline_id": event.pipeline_id, 
                "failure_type": failure_type
            })
        except Exception: logger.error("Recovery service failed")

    try:
        await http_request("POST", NOTIFICATION_SERVICE_URL, {
            "pipeline_id": event.pipeline_id,
            "status": result.get("status"),
            "failure_type": failure_type
        })
    except Exception: logger.error("Notification failed")

    await safe_set_status(redis_client, job_id, "completed", failure_type=failure_type)

async def process_pipeline(job_id: str, event: PipelineEvent, request_id: str):
    request_id_ctx.set(request_id)
    try:
        async with async_timeout(JOB_TIMEOUT):
            await _process_pipeline_inner(job_id, event)
    except Exception as exc:
        logger.exception("Pipeline processing error")
        await safe_set_status(app.state.redis, job_id, "failed", error=str(exc))

# ============================================================
# ENDPOINTS
# ============================================================
@app.post("/pipeline-event", status_code=202)
async def pipeline_event(event: PipelineEvent, background: BackgroundTasks, request: Request):
    rid = str(uuid.uuid4())
    request_id_ctx.set(rid)
    
    # Rate limit check
    client_ip = request.client.host if request.client else "unknown"
    key = f"ratelimit:{client_ip}"
    count = await app.state.redis.incr(key)
    if count == 1: await app.state.redis.expire(key, 60)
    if count > RATE_LIMIT: raise HTTPException(429, "Too many requests")

    job_id = str(uuid.uuid4())
    await app.state.redis.hset(job_id, mapping={
        "status": "processing",
        "submitted_at": datetime.now(timezone.utc).isoformat()
    })
    await app.state.redis.expire(job_id, JOB_TTL)

    background.add_task(process_pipeline, job_id, event, rid)
    return {"job_id": job_id, "status": "accepted"}

@app.get("/pipeline-status/{job_id}")
async def get_status(job_id: str):
    data = await app.state.redis.hgetall(job_id)
    if not data: raise HTTPException(404, "Job not found")
    return data

@app.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)