import os
import json
import hmac
import hashlib
import logging
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("github-adapter")

PIPELINE_CONTROLLER_URL = os.getenv("PIPELINE_CONTROLLER_URL", "http://localhost:9000/pipeline-event")
JENKINS_URL             = os.getenv("JENKINS_URL",             "http://localhost:8080")
WEBHOOK_SECRET          = os.getenv("GITHUB_WEBHOOK_SECRET",   "")

# Mapping from GitHub Actions workflow_run conclusion → pipeline status.
# "neutral" and "skipped" are treated as success (no recovery needed).
_CONCLUSION_TO_STATUS: dict[str, str] = {
    "success":   "SUCCESS",
    "neutral":   "SUCCESS",
    "skipped":   "SUCCESS",
    "failure":   "FAILED",
    "timed_out": "FAILED",
    "cancelled": "FAILED",
    "action_required": "FAILED",
}

app = FastAPI(title="GitHub Webhook Adapter", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not secret:
        return True
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _forward_to_controller(controller_payload: dict) -> dict:
    """POST a pipeline event to the Pipeline Controller and return the response."""
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(PIPELINE_CONTROLLER_URL, json=controller_payload)
            return {
                "forwarded":          resp.status_code == 202,
                "controller_response": resp.json() if resp.status_code == 202 else resp.text,
            }
        except Exception as exc:
            logger.error("Failed to reach Pipeline Controller: %s", exc)
            return {
                "forwarded": False,
                "error":     str(exc),
                "note":      "Pipeline Controller may not be running",
            }


def _make_event_id(prefix: str = "gh") -> str:
    return f"{prefix}-{str(uuid.uuid4())[:8]}"


@app.post("/pipeline-event")
async def github_webhook(request: Request):
    body      = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    event     = request.headers.get("X-GitHub-Event", "push")

    if WEBHOOK_SECRET and not verify_signature(body, signature, WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if event == "ping":
        return {"message": "pong — webhook connected successfully"}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # ── workflow_run: real CI/CD result from GitHub Actions ─────────────────
    # Triggered when a GitHub Actions workflow completes.  This gives us the
    # *actual* build conclusion so we forward the real status (not a hardcoded
    # FAILED) to the Pipeline Controller.
    if event == "workflow_run":
        action = payload.get("action", "")
        if action != "completed":
            return {"message": f"workflow_run action '{action}' ignored — only 'completed' is processed"}

        run      = payload.get("workflow_run", {})
        repo     = payload.get("repository", {})
        conclusion = run.get("conclusion", "failure")
        status   = _CONCLUSION_TO_STATUS.get(conclusion, "FAILED")

        repo_name  = repo.get("name", "unknown")
        run_number = int(run.get("run_number", 1))
        branch     = run.get("head_branch", "unknown")
        run_id     = run.get("id", 0)
        log_url    = run.get("logs_url") or f"{JENKINS_URL}/job/{repo_name}/{run_number}/consoleText"
        event_id   = f"gha-{run_id}"

        controller_payload = {
            "event_id":    event_id,
            "pipeline_id": repo_name,
            "run_number":  run_number,
            "status":      status,
            "log_url":     log_url,
        }

        logger.info(
            "workflow_run completed: repo=%s branch=%s run=%s conclusion=%s → status=%s",
            repo_name, branch, run_number, conclusion, status,
        )

        result = await _forward_to_controller(controller_payload)
        return {
            "adapter":     "github-webhook-adapter",
            "event_type":  "workflow_run",
            "event_id":    event_id,
            "pipeline_id": repo_name,
            "branch":      branch,
            "run_number":  run_number,
            "conclusion":  conclusion,
            "status":      status,
            **result,
        }

    # ── push: simulation / demo mode ────────────────────────────────────────
    # Push events don't carry a build result.  We forward them as FAILED so
    # the full recovery demo flow can be exercised from a simple git push.
    # In a real production setup you would configure workflow_run webhooks
    # instead and leave push events for branch-protection triggers only.
    if event != "push":
        return {"message": f"Event '{event}' ignored — only push and workflow_run events are processed"}

    repo_name  = payload.get("repository", {}).get("name", "unknown")
    branch     = payload.get("ref", "refs/heads/main").replace("refs/heads/", "")
    run_number = payload.get("after", "1")[:8]
    pusher     = payload.get("pusher", {}).get("name", "unknown")
    commit_msg = ""
    commits    = payload.get("commits", [])
    if commits:
        commit_msg = commits[-1].get("message", "")

    event_id = _make_event_id("gh")
    run_num  = abs(hash(run_number)) % 1000 + 1
    log_url  = f"{JENKINS_URL}/job/{repo_name}/lastBuild/consoleText"

    controller_payload = {
        "event_id":    event_id,
        "pipeline_id": repo_name,
        "run_number":  run_num,
        "status":      "FAILED",   # simulation: push events always exercise recovery
        "log_url":     log_url,
    }

    logger.info(
        "push event (demo mode): pusher=%s repo=%s branch=%s commit=%.50s",
        pusher, repo_name, branch, commit_msg,
    )

    result = await _forward_to_controller(controller_payload)
    return {
        "adapter":     "github-webhook-adapter",
        "event_type":  "push",
        "event_id":    event_id,
        "pipeline_id": repo_name,
        "branch":      branch,
        "pusher":      pusher,
        **result,
    }


@app.get("/health")
async def health():
    return {
        "service":   "github-adapter",
        "status":    "ok",
        "version":   "1.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
