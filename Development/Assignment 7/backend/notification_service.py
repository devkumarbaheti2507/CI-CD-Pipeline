import os
import smtplib
import logging
import asyncio
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from enum import Enum
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("notification-service")

EMAIL_ENABLED   = os.getenv("EMAIL_ENABLED",   "false").lower() == "true"
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_USER      = os.getenv("EMAIL_USER", "")
EMAIL_PASS      = os.getenv("EMAIL_PASS", "")
EMAIL_TO        = os.getenv("EMAIL_TO",   "")

SLACK_ENABLED     = os.getenv("SLACK_ENABLED",     "false").lower() == "true"
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

WEBHOOK_ENABLED = os.getenv("WEBHOOK_ENABLED", "false").lower() == "true"
WEBHOOK_URL     = os.getenv("WEBHOOK_URL",     "")

HTTP_TIMEOUT = 10
RETRY_COUNT  = 3


class PipelineStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED  = "FAILED"


class NotifyRequest(BaseModel):
    pipeline_id:        str
    status:             PipelineStatus
    failure_type:       Optional[str] = None
    recovery_triggered: bool          = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    yield
    await app.state.http.aclose()


app = FastAPI(title="Notification Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



def build_message(req: NotifyRequest) -> str:
    icon      = "✅" if req.status == PipelineStatus.SUCCESS else "❌"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"{icon} Pipeline Alert — {req.pipeline_id}",
        f"Status    : {req.status.value}",
    ]
    if req.failure_type:
        lines.append(f"Failure   : {req.failure_type}")
    lines.append(
        f"Recovery  : {'Triggered' if req.recovery_triggered else 'Not triggered'}"
    )
    lines.append(f"Time      : {timestamp}")
    return "\n".join(lines)


def send_email(req: NotifyRequest) -> bool:
    if not EMAIL_ENABLED:
        return False

    if not all([EMAIL_USER, EMAIL_PASS, EMAIL_TO]):
        logger.warning("Email skipped — configuration incomplete")
        return False

    subject = f"[CI/CD] {req.pipeline_id} — {req.status.value}"
    body    = build_message(req)

    msg = MIMEMultipart("alternative")
    msg["From"]    = EMAIL_USER
    msg["To"]      = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.sendmail(EMAIL_USER, EMAIL_TO, msg.as_string())
        logger.info("Email sent to %s", EMAIL_TO)
        return True
    except Exception as exc:
        logger.error("Email failed: %s", exc)
        return False


async def send_slack(req: NotifyRequest) -> bool:
    if not SLACK_ENABLED or not SLACK_WEBHOOK_URL:
        return False

    payload = {
        "attachments": [{
            "color": "#22c55e" if req.status == PipelineStatus.SUCCESS else "#ef4444",
            "text":  build_message(req),
        }]
    }

    for attempt in range(RETRY_COUNT):
        try:
            resp = await app.state.http.post(SLACK_WEBHOOK_URL, json=payload)
            resp.raise_for_status()
            logger.info("Slack notification sent")
            return True
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                logger.error("Slack permanent error %s: %s", exc.response.status_code, exc)
                return False
            if attempt == RETRY_COUNT - 1:
                logger.error("Slack failed after retries: %s", exc)
        except httpx.RequestError as exc:
            if attempt == RETRY_COUNT - 1:
                logger.error("Slack request error: %s", exc)
        await asyncio.sleep(2 ** attempt)

    return False


async def send_webhook(req: NotifyRequest) -> bool:
    if not WEBHOOK_ENABLED or not WEBHOOK_URL:
        return False

    payload = {
        "pipeline_id":        req.pipeline_id,
        "status":             req.status.value,
        "failure_type":       req.failure_type,
        "recovery_triggered": req.recovery_triggered,
        "sent_at":            datetime.now(timezone.utc).isoformat(),
    }

    for attempt in range(RETRY_COUNT):
        try:
            resp = await app.state.http.post(WEBHOOK_URL, json=payload)
            resp.raise_for_status()
            logger.info("Webhook sent")
            return True
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                logger.error("Webhook permanent error %s: %s", exc.response.status_code, exc)
                return False
            if attempt == RETRY_COUNT - 1:
                logger.error("Webhook failed after retries: %s", exc)
        except httpx.RequestError as exc:
            if attempt == RETRY_COUNT - 1:
                logger.error("Webhook request error: %s", exc)
        await asyncio.sleep(2 ** attempt)

    return False


@app.post("/notify")
async def notify(req: NotifyRequest):
    logger.info(
        "Notification received: pipeline=%s status=%s",
        req.pipeline_id, req.status.value,
    )

    loop = asyncio.get_running_loop()

    email_result, slack_result, webhook_result = await asyncio.gather(
        loop.run_in_executor(None, send_email, req),
        send_slack(req),
        send_webhook(req),
    )

    results = {
        "email":   email_result,
        "slack":   slack_result,
        "webhook": webhook_result,
    }

    logger.info("Dispatch complete: %s", results)

    return {
        "status":      "ok",
        "pipeline_id": req.pipeline_id,
        "channels":    results,
        "any_sent":    any(results.values()),
        "sent_at":     datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
async def health():
    return {
        "service": "notification-service",
        "status":  "ok",
        "channels": {
            "email":   EMAIL_ENABLED and bool(EMAIL_USER and EMAIL_TO),
            "slack":   SLACK_ENABLED and bool(SLACK_WEBHOOK_URL),
            "webhook": WEBHOOK_ENABLED and bool(WEBHOOK_URL),
        },
    }