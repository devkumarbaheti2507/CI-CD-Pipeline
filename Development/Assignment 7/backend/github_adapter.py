import os
import json
import hmac
import hashlib
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

PIPELINE_CONTROLLER_URL = os.getenv("PIPELINE_CONTROLLER_URL", "http://localhost:9000/pipeline-event")
JENKINS_URL             = os.getenv("JENKINS_URL",             "http://localhost:8080")
WEBHOOK_SECRET          = os.getenv("GITHUB_WEBHOOK_SECRET",   "")

app = FastAPI(title="GitHub Webhook Adapter", version="1.0.0")

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

@app.post("/pipeline-event")
async def github_webhook(request: Request):
    body      = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    event     = request.headers.get("X-GitHub-Event", "push")

    if WEBHOOK_SECRET and not verify_signature(body, signature, WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if event == "ping":
        return {"message": "pong — webhook connected successfully"}

    if event != "push":
        return {"message": f"Event '{event}' ignored — only push events are processed"}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    repo_name  = payload.get("repository", {}).get("name", "unknown")
    branch     = payload.get("ref", "refs/heads/main").replace("refs/heads/", "")
    run_number = payload.get("after", "1")[:8]
    pusher     = payload.get("pusher", {}).get("name", "unknown")
    commit_msg = ""
    commits    = payload.get("commits", [])
    if commits:
        commit_msg = commits[-1].get("message", "")

    import uuid, re
    event_id   = f"gh-{str(uuid.uuid4())[:8]}"
    run_num    = abs(hash(run_number)) % 1000 + 1
    log_url    = f"{JENKINS_URL}/job/{repo_name}/lastBuild/consoleText"

    controller_payload = {
        "event_id":   event_id,
        "pipeline_id": repo_name,
        "run_number": run_num,
        "status":     "FAILED",
        "log_url":    log_url,
    }

    print(f"[Adapter] Push from {pusher} to {branch} — {commit_msg[:50]}")
    print(f"[Adapter] Forwarding to Pipeline Controller: {controller_payload}")

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(PIPELINE_CONTROLLER_URL, json=controller_payload)
            return {
                "adapter":    "github-webhook-adapter",
                "event_id":   event_id,
                "pipeline_id": repo_name,
                "branch":     branch,
                "pusher":     pusher,
                "forwarded":  resp.status_code == 202,
                "controller_response": resp.json() if resp.status_code == 202 else resp.text,
            }
        except Exception as exc:
            return {
                "adapter": "github-webhook-adapter",
                "error":   str(exc),
                "note":    "Pipeline Controller may not be running",
            }

@app.get("/health")
async def health():
    return {"service": "github-adapter", "status": "ok"}
