import os
import logging
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict
from datetime import datetime

LOG_ANALYZER_URL = os.getenv("LOG_ANALYZER_URL", "http://log-analyzer:5001/analyze")
RECOVERY_SERVICE_URL = os.getenv("RECOVERY_SERVICE_URL", "http://recovery-manager:6000/recover")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:7000/notify")



logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("PipelineController")



app = FastAPI(title="Pipeline Controller Service")




class PipelineEvent(BaseModel):
    pipeline_id: str
    status: str
    log_url: str   # Jenkins log endpoint



def fetch_pipeline_logs(log_url: str) -> str:
    try:
        response = requests.get(log_url, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logger.error(f"Failed to fetch logs: {e}")
        raise


def analyze_logs(log_text: str) -> Dict:
    try:
        response = requests.post(
            LOG_ANALYZER_URL,
            json={"log": log_text},
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"LogAnalyzer unavailable: {e}")
        raise



def trigger_recovery(pipeline_id: str, failure_type: str):
    try:
        requests.post(
            RECOVERY_SERVICE_URL,
            json={
                "pipeline_id": pipeline_id,
                "failure_type": failure_type
            },
            timeout=20
        )
    except requests.RequestException as e:
        logger.error(f"Recovery service failed: {e}")



def send_notification(pipeline_id: str, status: str, failure_type: str):
    try:
        requests.post(
            NOTIFICATION_SERVICE_URL,
            json={
                "pipeline_id": pipeline_id,
                "status": status,
                "failure_type": failure_type
            },
            timeout=20
        )
    except requests.RequestException as e:
        logger.error(f"Notification service failed: {e}")



@app.post("/pipeline-event")
def handle_pipeline_event(event: PipelineEvent):

    logger.info(f"Received pipeline event: {event.pipeline_id}")

    if event.status == "SUCCESS":
        return {
            "message": "Pipeline succeeded. No action required."
        }

    # Step 1: Fetch Logs
    logs = fetch_pipeline_logs(event.log_url)

    # Step 2: Analyze Logs
    analysis = analyze_logs(logs)

    failure_type = analysis.get("failure_type")

    # Step 3: Trigger Recovery
    if analysis.get("status") == "FAILED":
        trigger_recovery(event.pipeline_id, failure_type)

    # Step 4: Notify
    send_notification(event.pipeline_id, analysis.get("status"), failure_type)

    return {
        "pipeline_id": event.pipeline_id,
        "analysis": analysis,
        "processed_at": datetime.utcnow().isoformat() + "Z"
    }
