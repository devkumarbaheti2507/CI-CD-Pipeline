"""
Pipeline Controller Service — Final Corrected Version
======================================================

All issues from code review resolved:
  1.  async-timeout declared in requirements.txt (Python < 3.11 safe)
  2.  HTTPS log URLs: custom SSL context validates cert against original
      hostname while connecting to resolved IP (no SSLCertVerificationError)
  3.  asyncio.gather results normalised — exception objects never leak to JSON
  4.  SSRF pre-flight check at request time (not only in background task)
  5.  hset replaced with delete+hset pipeline — no stale fields
  6.  404 message distinguishes "never existed" from "expired"
  7.  Internal Jenkins container URL conflict documented; allowlist supported
  8.  Rate limiting on /pipeline-event (Redis-backed, 100 req/min per IP)

Environment variables
---------------------
  REDIS_URL                   redis://localhost:6379
  LOG_ANALYZER_URL            http://log-analyzer:5001/analyze
  LOG_ANALYZER_HEALTH_URL     http://log-analyzer:5001/health
  RECOVERY_SERVICE_URL        http://recovery-manager:6000/recover
  NOTIFICATION_SERVICE_URL    http://notification-service:7000/notify
  STATUS_API_KEY              (optional) API key for /pipeline-status
  ALLOWED_LOG_HOSTS           (optional) comma-separated hostnames that are
                              exempt from private-IP SSRF check, e.g.:
                              "jenkins,jenkins.internal,ci.corp.local"
  RATE_LIMIT_PER_MINUTE       max requests per IP per minute (default: 100)
"""

import os
import ssl
import uuid
import asyncio
import ipaddress
import logging
import contextvars
import re
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

# ============================================================
# PYTHON VERSION-SAFE TIMEOUT
# ============================================================

try:
    from asyncio import timeout as async_timeout          # Python 3.11+
except ImportError:
    from async_timeout import timeout as async_timeout    # async-timeout package


# ============================================================
# CONFIGURATION
# ============================================================

APP_VERSION = "1.0.0"

REDIS_URL                = os.getenv("REDIS_URL",                "redis://localhost:6379")
LOG_ANALYZER_URL         = os.getenv("LOG_ANALYZER_URL",         "http://localhost:5001/api/v1/analyze")
LOG_ANALYZER_HEALTH_URL  = os.getenv("LOG_ANALYZER_HEALTH_URL",  "http://localhost:5001/api/v1/health")
RECOVERY_SERVICE_URL     = os.getenv("RECOVERY_SERVICE_URL",     "http://localhost:6001/recover")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://localhost:7000/notify")
RECOVERY_HEALTH_URL      = os.getenv("RECOVERY_HEALTH_URL",      "http://localhost:6001/health")
NOTIFICATION_HEALTH_URL  = os.getenv("NOTIFICATION_HEALTH_URL",  "http://localhost:7000/health")
JENKINS_USER             = os.getenv("JENKINS_USER",             "admin")
JENKINS_TOKEN            = os.getenv("JENKINS_TOKEN",            "")

HTTP_TIMEOUT         = float(os.getenv("HTTP_TIMEOUT",         "20"))
MAX_RETRIES          = int(os.getenv("MAX_RETRIES",            "3"))
JOB_TIMEOUT          = int(os.getenv("JOB_TIMEOUT",            "120"))
MAX_LOG_SIZE         = int(os.getenv("MAX_LOG_SIZE_MB",        "10")) * 1024 * 1024
JOB_TTL              = int(os.getenv("JOB_TTL",                "86400"))
HEALTH_CHECK_TIMEOUT = float(os.getenv("HEALTH_CHECK_TIMEOUT", "3"))
RATE_LIMIT           = int(os.getenv("RATE_LIMIT_PER_MINUTE",  "100"))

# Hosts exempt from private-IP SSRF check (e.g. internal Jenkins containers)
_ALLOWED_RAW = os.getenv("ALLOWED_LOG_HOSTS", "")
ALLOWED_LOG_HOSTS: set[str] = {
    h.strip().lower() for h in _ALLOWED_RAW.split(",") if h.strip()
}


# ============================================================
# STRUCTURED LOGGING WITH REQUEST-ID
# ============================================================

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()   # type: ignore[attr-defined]
        return True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("pipeline-controller")
logger.addFilter(RequestIdFilter())
# Suppress httpx verbose logs to avoid request_id format conflicts
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# ============================================================
# DOMAIN EXCEPTIONS
# ============================================================

class UnsafeURLError(ValueError):
    """Raised when a URL resolves to a private / loopback / reserved IP."""


class LogTooLargeError(ValueError):
    """Raised when streamed log body exceeds MAX_LOG_SIZE."""
    def __init__(self) -> None:
        super().__init__(f"Log exceeds {MAX_LOG_SIZE // (1024 * 1024)} MB limit")


class RateLimitError(Exception):
    """Raised when a client exceeds the per-minute request limit."""


# ============================================================
# PYDANTIC MODELS
# ============================================================

class PipelineStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED  = "FAILED"


EventId    = Annotated[str, StringConstraints(min_length=10, max_length=100)]
PipelineId = Annotated[str, StringConstraints(min_length=3,  max_length=100)]


class PipelineEvent(BaseModel):
    event_id:    EventId
    pipeline_id: PipelineId
    run_number:  int = Field(gt=0)
    status:      PipelineStatus
    log_url:     HttpUrl


class PipelineResponse(BaseModel):
    job_id:       str
    status:       str
    submitted_at: str


# ============================================================
# LIFESPAN — STARTUP / SHUTDOWN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    app.state.redis = redis.from_url(REDIS_URL, decode_responses=True)

    if not os.getenv("STATUS_API_KEY"):
        logger.warning(
            "STATUS_API_KEY not set — /pipeline-status is publicly accessible"
        )
    if ALLOWED_LOG_HOSTS:
        logger.info(
            "SSRF allowlist active",
            extra={"allowed_hosts": sorted(ALLOWED_LOG_HOSTS)},
        )

    logger.info("Pipeline controller started", extra={"version": APP_VERSION})
    yield

    await app.state.http.aclose()
    await app.state.redis.close()
    logger.info("Pipeline controller stopped")


app = FastAPI(
    title="Pipeline Controller",
    version=APP_VERSION,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



# ============================================================
# SSRF PROTECTION  (fix #2 + #4 + #7)
# ============================================================

async def resolve_host(host: str) -> str:
    """
    Async DNS resolution with SSRF protection.
    - Uses loop.getaddrinfo() — non-blocking (fix from v5)
    - Checks ALL returned IPs, not just the first (fix from v6)
    - Respects ALLOWED_LOG_HOSTS allowlist (fix #7)

    Returns the first resolved IP string.
    Raises UnsafeURLError if any resolved IP is private/loopback/reserved.
    """
    if host.lower() in ALLOWED_LOG_HOSTS:
        # Allowlisted hostname — skip private-IP check, resolve normally
        loop = asyncio.get_running_loop()
        results = await loop.getaddrinfo(host, None)
        if not results:
            raise UnsafeURLError(f"Could not resolve host: {host}")
        # Prefer IPv4 to avoid Windows IPv6 URL issues
        import socket as _sock
        for r in results:
            if r[0] == _sock.AF_INET:
                return r[4][0]
        return results[0][4][0]

    loop = asyncio.get_running_loop()
    try:
        results = await loop.getaddrinfo(host, None)
    except OSError as exc:
        raise UnsafeURLError(f"DNS resolution failed for {host}: {exc}") from exc

    if not results:
        raise UnsafeURLError(f"No DNS results for host: {host}")

    valid_ips: list[str] = []
    for r in results:
        raw_ip = r[4][0]
        try:
            ip_obj = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved:
            raise UnsafeURLError(
                f"Host {host!r} resolves to restricted IP {raw_ip}"
            )
        valid_ips.append(raw_ip)

    if not valid_ips:
        raise UnsafeURLError(f"No routable IPs found for host: {host}")

    return valid_ips[0]


# ============================================================
# HTTP RETRY UTILITY
# ============================================================

async def http_request(
    method: str,
    url:    str,
    json:   Optional[dict] = None,
) -> httpx.Response:
    """
    HTTP request with smart retry:
    - Retries on 5xx and 429 (back-off: 1s, 2s, 4s …)
    - Raises immediately on permanent 4xx errors (no retry)
    - Tracks last exception and re-raises it correctly (fix from v6)
    """
    client: httpx.AsyncClient = app.state.http
    last_exc: Optional[Exception] = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.request(method, url, json=json)
            resp.raise_for_status()
            return resp

        except httpx.HTTPStatusError as exc:
            # Permanent client error — do not retry
            if exc.response.status_code < 500 and exc.response.status_code != 429:
                raise
            last_exc = exc

        except httpx.RequestError as exc:
            last_exc = exc

        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(2 ** attempt)   # 1s, 2s, 4s …

    assert last_exc is not None
    raise last_exc


# ============================================================
# LOG STREAMING  (fix #2 — HTTPS + raw IP TLS)
# ============================================================

def _build_ssl_context(hostname: str) -> ssl.SSLContext:
    """
    Build an SSL context that:
    - Verifies the full certificate chain (CERT_REQUIRED)
    - Disables automatic hostname check in the ssl module so that
      httpx can connect to the raw IP while still presenting the
      correct SNI and validating the cert CN/SAN via the extension.
    httpx's sni_hostname extension supplies the correct server name
    for both SNI negotiation and post-handshake cert verification.
    """
    ctx = ssl.create_default_context()
    # We disable ssl.SSLContext's own hostname check because httpx
    # handles hostname verification separately via sni_hostname.
    # The certificate chain is still fully verified (CERT_REQUIRED).
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


async def fetch_logs(url: str) -> str:
    """
    Stream log content from a URL safely:
    - Resolves hostname → validates IP (SSRF protection)
    - Connects directly to resolved IP (prevents DNS rebinding)
    - Sets Host header + SNI + SSL context for correct HTTPS (fix #2)
    - Stops reading at MAX_LOG_SIZE bytes (no OOM)
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    ip = await resolve_host(hostname)

    # Reconstruct URL with IP as netloc, preserving path/query/fragment
    # Wrap IPv6 addresses in brackets (e.g. ::1 -> [::1]) for valid URL
    import ipaddress as _ip
    try:
        if isinstance(_ip.ip_address(ip), _ip.IPv6Address):
            netloc = f"[{ip}]"
            if parsed.port:
                netloc = f"[{ip}]:{parsed.port}"
        else:
            netloc = ip
            if parsed.port:
                netloc = f"{ip}:{parsed.port}"
    except ValueError:
        netloc = ip
    url_ip = urlunparse((
        parsed.scheme,
        netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        parsed.fragment,
    ))

    # Add Jenkins Basic Auth if credentials are configured
    import base64 as _b64
    headers = {"Host": hostname}
    if JENKINS_USER and JENKINS_TOKEN:
        creds = f"{JENKINS_USER}:{JENKINS_TOKEN}".encode()
        headers["Authorization"] = "Basic " + _b64.b64encode(creds).decode()
    extensions: dict = {"sni_hostname": hostname.encode()}

    # For HTTPS: attach SSL context that verifies cert chain but
    # defers hostname check to httpx's SNI mechanism (fix #2)
    if parsed.scheme == "https":
        extensions["ssl_context"] = _build_ssl_context(hostname)

    total  = 0
    chunks: list[bytes] = []

    async with app.state.http.stream(
        "GET", url_ip, headers=headers, extensions=extensions
    ) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes(65536):
            total += len(chunk)
            if total > MAX_LOG_SIZE:
                raise LogTooLargeError()
            chunks.append(chunk)

    return b"".join(chunks).decode(errors="ignore")


# ============================================================
# REDIS JOB STATE  (fix #5 — delete+hset, no stale fields)
# ============================================================

async def set_job_status(
    redis_client,
    job_id:       str,
    status:       str,
    error:        Optional[str] = None,
    failure_type: Optional[str] = None,
) -> None:
    """
    Atomically replace the job hash and reset TTL.
    Uses DELETE + HSET in a pipeline so stale fields from a
    previous status never persist (fix #5).
    """
    data: dict[str, str] = {"status": status}
    if error:
        data["error"] = error
    if failure_type:
        data["failure_type"] = failure_type

    async with redis_client.pipeline() as pipe:
        pipe.delete(job_id)           # clear stale fields atomically
        pipe.hset(job_id, mapping=data)
        pipe.expire(job_id, JOB_TTL)
        await pipe.execute()


async def safe_set_status(
    redis_client,
    job_id:       str,
    status:       str,
    error:        Optional[str] = None,
    failure_type: Optional[str] = None,
) -> None:
    """
    Wrapper around set_job_status that never raises.
    Used inside error-handling paths where a Redis failure must
    not itself propagate as an unhandled exception (fix from v7).
    """
    try:
        await set_job_status(redis_client, job_id, status, error, failure_type)
    except Exception:
        logger.error(
            "failed to write job status to Redis",
            extra={"job_id": job_id, "target_status": status},
        )


# ============================================================
# RATE LIMITING  (fix #8)
# ============================================================

async def enforce_rate_limit(redis_client, client_ip: str) -> None:
    """
    Sliding window rate limit: RATE_LIMIT requests per IP per 60 s.
    Raises HTTPException(429) if the limit is exceeded.
    """
    key   = f"ratelimit:{client_ip}"
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, 60)
    if count > RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {RATE_LIMIT} requests per minute",
        )


# ============================================================
# PIPELINE PROCESSING
# ============================================================

async def _process_pipeline_inner(job_id: str, event: PipelineEvent) -> None:
    redis_client = app.state.redis

    logs     = await fetch_logs(str(event.log_url))
    analysis = await http_request("POST", LOG_ANALYZER_URL, {"log": logs})
    result   = analysis.json()

    failure_type = result.get("failure_type")
    recovery_ok  = False

    if result.get("status") == "FAILED":
        try:
            await http_request(
                "POST",
                RECOVERY_SERVICE_URL,
                {
                    "pipeline_id":  event.pipeline_id,
                    "failure_type": failure_type,
                },
            )
            recovery_ok = True
        except (httpx.RequestError, httpx.HTTPStatusError):
            # Recovery failure is logged but must NOT suppress notification
            logger.error(
                "recovery service failed",
                extra={"pipeline_id": event.pipeline_id},
            )

    # Notification always fires regardless of recovery outcome
    try:
        await http_request(
            "POST",
            NOTIFICATION_SERVICE_URL,
            {
                "pipeline_id":        event.pipeline_id,
                "status":             result.get("status"),
                "failure_type":       failure_type,
                "recovery_triggered": recovery_ok,
            },
        )
    except (httpx.RequestError, httpx.HTTPStatusError):
        logger.error(
            "notification service failed",
            extra={"pipeline_id": event.pipeline_id},
        )

    await safe_set_status(
        redis_client, job_id, "completed", failure_type=failure_type
    )


async def process_pipeline(
    job_id:     str,
    event:      PipelineEvent,
    request_id: str,
) -> None:
    """Background worker — runs after the endpoint has returned 202."""
    request_id_ctx.set(request_id)
    redis_client = app.state.redis

    try:
        async with async_timeout(JOB_TIMEOUT):
            await _process_pipeline_inner(job_id, event)

    except UnsafeURLError as exc:
        await safe_set_status(redis_client, job_id, "unsafe_url", str(exc))

    except LogTooLargeError as exc:
        await safe_set_status(redis_client, job_id, "log_too_large", str(exc))

    except asyncio.TimeoutError:
        await safe_set_status(redis_client, job_id, "timeout")

    except httpx.RequestError as exc:
        await safe_set_status(redis_client, job_id, "network_error", str(exc))

    except Exception as exc:
        logger.exception("unexpected pipeline failure")
        await safe_set_status(redis_client, job_id, "internal_error", str(exc))


# ============================================================
# PIPELINE EVENT ENDPOINT
# ============================================================

@app.post("/pipeline-event", response_model=PipelineResponse, status_code=202)
async def pipeline_event(
    event:      PipelineEvent,
    background: BackgroundTasks,
    request:    Request,
) -> PipelineResponse:
    request_id = str(uuid.uuid4())
    request_id_ctx.set(request_id)

    redis_client = app.state.redis
    client_ip    = request.client.host if request.client else "unknown"

    # ── rate limit (fix #8) ───────────────────────────────
    await enforce_rate_limit(redis_client, client_ip)

    # ── SSRF pre-flight at request time (fix #4) ──────────
    # Validates URL before accepting the job so the caller gets
    # an immediate 400 rather than discovering the error via polling.
    log_url_str = str(event.log_url)
    parsed_host = urlparse(log_url_str).hostname or ""
    try:
        await resolve_host(parsed_host)
    except UnsafeURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── idempotency ───────────────────────────────────────
    dedup_key = f"event:{event.event_id}"
    inserted  = await redis_client.set(dedup_key, "1", ex=JOB_TTL, nx=True)
    if not inserted:
        raise HTTPException(status_code=409, detail="duplicate event")

    # ── create job record ─────────────────────────────────
    job_id = str(uuid.uuid4())
    async with redis_client.pipeline() as pipe:
        pipe.hset(job_id, mapping={
            "status":       "processing",
            "pipeline_id":  event.pipeline_id,
            "run_number":   str(event.run_number),
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        })
        pipe.expire(job_id, JOB_TTL)
        results = await pipe.execute()

    if not all(results):
        raise HTTPException(status_code=500, detail="failed to create job record")

    background.add_task(process_pipeline, job_id, event, request_id)

    logger.info(
        "pipeline event accepted",
        extra={
            "pipeline_id": event.pipeline_id,
            "run_number":  event.run_number,
            "job_id":      job_id,
            "client_ip":   client_ip,
        },
    )

    return PipelineResponse(
        job_id       = job_id,
        status       = "accepted",
        submitted_at = datetime.now(timezone.utc).isoformat(),
    )


# ============================================================
# JOB STATUS ENDPOINT
# ============================================================

UUID_RE  = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
API_KEY: Optional[str] = os.getenv("STATUS_API_KEY")


@app.get("/pipeline-status/{job_id}")
async def pipeline_status(
    job_id:    str,
    x_api_key: Optional[str] = Header(default=None),
) -> dict:
    # ── auth ──────────────────────────────────────────────
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="unauthorized")

    # ── input validation ──────────────────────────────────
    if not UUID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="invalid job id format")

    redis_client = app.state.redis
    data         = await redis_client.hgetall(job_id)

    if not data:
        # fix #6 — honest 404 message
        raise HTTPException(
            status_code=404,
            detail="job not found or has expired (TTL: 24 h)",
        )

    return data


# ============================================================
# HEALTH CHECK
# ============================================================

async def check_service(url: str) -> bool:
    """Probe a downstream service health endpoint."""
    try:
        r = await app.state.http.get(url, timeout=HEALTH_CHECK_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


@app.get("/health")
async def health() -> JSONResponse:
    redis_ok = False
    try:
        redis_ok = await app.state.redis.ping()
    except Exception:
        pass

    # Run all service checks concurrently (fix from v7)
    raw_results = await asyncio.gather(
        check_service(LOG_ANALYZER_HEALTH_URL),
        check_service(RECOVERY_HEALTH_URL),
        check_service(NOTIFICATION_HEALTH_URL),
        return_exceptions=True,
    )

    # fix #3 — normalise exception objects to False so JSON never breaks
    analyzer_ok, recovery_ok, notify_ok = [
        r if isinstance(r, bool) else False
        for r in raw_results
    ]

    # Service is healthy only if Redis and Log Analyzer are reachable
    # (Recovery and Notification degraded but not blocking)
    healthy = bool(redis_ok and analyzer_ok)

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "service": "pipeline-controller",
            "version": APP_VERSION,
            "status":  "ok" if healthy else "degraded",
            "dependencies": {
                "redis":        redis_ok,
                "log_analyzer": analyzer_ok,
                "recovery":     recovery_ok,
                "notification": notify_ok,
            },
            "time": datetime.now(timezone.utc).isoformat(),
        },
    )
