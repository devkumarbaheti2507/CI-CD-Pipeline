import os
import asyncio
import logging
import uuid
from typing import Optional, Dict
from datetime import datetime, timezone
from enum import Enum

import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel, HttpUrl, constr



LOG_ANALYZER_URL = os.getenv("LOG_ANALYZER_URL", "http://log-analyzer:5001/analyze")
RECOVERY_SERVICE_URL = os.getenv("RECOVERY_SERVICE_URL", "http://recovery-manager:6000/recover")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:7000/notify")

MAX_RETRIES = 3
TIMEOUT = 20.0



logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("PipelineController")


app = FastAPI(title="Pipeline Controller Service")


class PipelineStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RUNNING = "RUNNING"

class PipelineEvent(BaseModel):
    pipeline_id: constr(min_length=3, max_length=100)
    status: PipelineStatus
    log_url: HttpUrl   # prevents SSRF schemes like file://

class PipelineResponse(BaseModel):
    pipeline_id: str
    status: str
    failure_type: Optional[str]
    recovery_triggered: bool
    notification_sent: bool
    processed_at: str
    request_id: str



processed_events = set()



async def http_post_with_retry(url: str, json_data: Dict, headers: Dict) -> httpx.Response:
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(url, json=json_data, headers=headers)
                response.raise_for_status()
                return response
        except httpx.RequestError as e:
            if attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(2 ** attempt)

async def http_get_with_retry(url: str, headers: Dict) -> httpx.Response:
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response
        except httpx.RequestError:
            if attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(2 ** attempt)



async def process_pipeline(event: PipelineEvent, request_id: str):

    headers = {"X-Request-ID": request_id}

    # Fetch logs
    try:
        log_response = await http_get_with_retry(str(event.log_url), headers)
        logs = log_response.text
    except Exception as e:
        logger.error("Log fetch failed", extra={"pipeline_id": event.pipeline_id})
        return

    # Analyze logs
    try:
        analysis_response = await http_post_with_retry(
            LOG_ANALYZER_URL,
            {"log": logs},
            headers
        )
        analysis = analysis_response.json()
    except Exception:
        logger.error("Log analysis failed", extra={"pipeline_id": event.pipeline_id})
        return

    failure_type = analysis.get("failure_type")
    recovery_triggered = False
    notification_sent = False

    if analysis.get("status") == "FAILED":
        try:
            await http_post_with_retry(
                RECOVERY_SERVICE_URL,
                {
                    "pipeline_id": event.pipeline_id,
                    "failure_type": failure_type
                },
                headers
            )
            recovery_triggered = True
        except Exception:
            logger.error("Recovery failed", extra={"pipeline_id": event.pipeline_id})

    try:
        await http_post_with_retry(
            NOTIFICATION_SERVICE_URL,
            {
                "pipeline_id": event.pipeline_id,
                "status": analysis.get("status"),
                "failure_type": failure_type
            },
            headers
        )
        notification_sent = True
    except Exception:
        logger.error("Notification failed", extra={"pipeline_id": event.pipeline_id})


@app.post("/pipeline-event", response_model=PipelineResponse)
async def handle_pipeline_event(
    event: PipelineEvent,
    background_tasks: BackgroundTasks,
    request: Request
):

    request_id = str(uuid.uuid4())

    # Idempotency Check
    if event.pipeline_id in processed_events:
        raise HTTPException(status_code=409, detail="Duplicate pipeline event")

    processed_events.add(event.pipeline_id)

    logger.info(
        "Pipeline event received",
        extra={"pipeline_id": event.pipeline_id, "request_id": request_id}
    )

    if event.status == PipelineStatus.SUCCESS:
        return PipelineResponse(
            pipeline_id=event.pipeline_id,
            status="SUCCESS",
            failure_type=None,
            recovery_triggered=False,
            notification_sent=False,
            processed_at=datetime.now(timezone.utc).isoformat(),
            request_id=request_id
        )

    background_tasks.add_task(process_pipeline, event, request_id)

    return PipelineResponse(
        pipeline_id=event.pipeline_id,
        status="PROCESSING",
        failure_type=None,
        recovery_triggered=False,
        notification_sent=False,
        processed_at=datetime.now(timezone.utc).isoformat(),
        request_id=request_id
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "pipeline-controller",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
