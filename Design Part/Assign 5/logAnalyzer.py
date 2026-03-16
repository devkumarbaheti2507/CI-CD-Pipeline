import re
import os
import json
import datetime
from pathlib import Path
from typing import Dict, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", 5001))

FAILURE_PATTERNS = {
    "BUILD_ERROR": [
        r"error:.*compilation failed",
        r"make\[.*\].*Error",
        r"BUILD FAILED",
        r"Cannot find module",
        r"ModuleNotFoundError",
        r"ImportError",
    ],
    "TEST_FAILURE": [
        r"FAILED\s+tests/",
        r"\d+ failed",
        r"AssertionError",
        r"FAIL:\s+test_",
    ],
    "DEPLOY_ERROR": [
        r"deployment failed",
        r"Error response from daemon",
        r"kubectl.*Error",
        r"container exited with code [^0]",
    ],
    "DEPENDENCY_ERROR": [
        r"Could not resolve",
        r"npm ERR!",
        r"pip.*ERROR",
        r"Package.*not found",
    ],
    "TIMEOUT": [
        r"timeout exceeded",
        r"Timed out",
        r"ETIMEDOUT",
    ],
}

app = FastAPI(title="CI/CD Log Analyzer", version="1.0")

class LogRequest(BaseModel):
    log: str

def analyze_log(log_text: str) -> Dict:
    lines = log_text.splitlines()
    detected = []

    for line_no, line in enumerate(lines, start=1):
        for failure_type, patterns in FAILURE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    detected.append({
                        "line": line_no,
                        "content": line.strip(),
                        "failure_type": failure_type,
                    })

    seen = set()
    unique = []
    for d in detected:
        if d["line"] not in seen:
            seen.add(d["line"])
            unique.append(d)

    if unique:
        priority = ["DEPLOY_ERROR", "BUILD_ERROR",
                    "TEST_FAILURE", "DEPENDENCY_ERROR", "TIMEOUT"]
        found_types = {d["failure_type"] for d in unique}
        overall_type = next((t for t in priority if t in found_types),
                            unique[0]["failure_type"])
        status = "FAILED"
    else:
        overall_type = None
        status = "SUCCESS"

    return {
        "status": status,
        "failure_type": overall_type,
        "total_lines": len(lines),
        "failures_found": len(unique),
        "details": unique,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }

@app.get("/health")
def health():
    return {"status": "ok", "service": "Log Analyzer"}

@app.post("/analyze")
def analyze(request: LogRequest):
    if not request.log:
        raise HTTPException(400, "Log text is empty")
    return analyze_log(request.log)

@app.get("/analyze-file")
def analyze_file(path: str):
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, "File not found")
    return analyze_log(p.read_text())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("log_analyzer:app", host=APP_HOST, port=APP_PORT, reload=False)
