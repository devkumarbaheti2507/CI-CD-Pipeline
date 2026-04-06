from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import json
from datetime import datetime, timezone

# Import microservice FastAPI apps
from failure_classifier import app as failure_app
from github_adapter import app as github_app
from notification_service import app as notification_app
from pipeline_controller import app as pipeline_app
from recovery_manager import app as recovery_app

# Import log analyzer module directly since it uses standard http.server
import log_analyzer

# Create the main Vercel entrypoint app
app = FastAPI(title="CI/CD Backend Monolith", version="1.0.0")

# Mount existing FastAPI microservices to specific routing paths
app.mount("/classifier", failure_app)
app.mount("/github", github_app)
app.mount("/notification", notification_app)
app.mount("/pipeline", pipeline_app)
app.mount("/recovery", recovery_app)

@app.get("/")
def root():
    """Health check endpoint for the main Vercel app."""
    return {
        "status": "online",
        "message": "CI/CD Backend Monolith is running on Vercel.",
        "services_mounted": [
            "/classifier", 
            "/github", 
            "/notification", 
            "/pipeline", 
            "/recovery",
            "/api/v1/analyze"
        ]
    }

# --------------------------------------------------------------------------------
# Log Analyzer Custom Vercel Adapters
# log_analyzer.py uses python's http.server. We expose its logic here via FastAPI.
# --------------------------------------------------------------------------------

@app.post("/api/v1/analyze")
async def analyze_logs_endpoint(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Request body must be valid JSON"}, status_code=400)
    
    log_text = payload.get("log") or payload.get("log_text")
    fmt_hint = payload.get("format", "auto")

    if not log_text:
        return JSONResponse({"error": "Missing 'log' or 'log_text' field in JSON payload"}, status_code=400)
    
    result = log_analyzer.analyze(log_text=log_text, fmt_hint=fmt_hint)
    return result.to_dict()

@app.post("/api/v1/analyze/batch")
async def analyze_batch_endpoint(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Request body must be valid JSON"}, status_code=400)
    
    logs = payload.get("logs", [])
    if not isinstance(logs, list):
        return JSONResponse({"error": "'logs' must be an array"}, status_code=400)
    
    if not logs:
        return JSONResponse({"error": "'logs' array cannot be empty"}, status_code=400)
    
    if len(logs) > 50:
        return JSONResponse({"error": "Max 50 logs allowed per batch"}, status_code=413) 
    
    results = []
    for snippet in logs:
        text = snippet.get("log") or snippet.get("log_text")
        if text:
            ans = log_analyzer.analyze(log_text=text, fmt_hint=snippet.get("format", "auto"))
            results.append(ans.to_dict())
            
    return {"status": "SUCCESS", "analyzed": len(results), "results": results}

@app.get("/api/v1/health")
def log_health_endpoint():
    return {
        "status": "healthy",
        "service": log_analyzer.CONFIG.service_name,
        "version": log_analyzer.CONFIG.version,
        "uptime_seconds": round(log_analyzer.METRICS.uptime_seconds(), 2),
        "rules_loaded": len(log_analyzer.RULES.all_rules()),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
