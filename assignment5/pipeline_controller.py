import subprocess
import datetime
import json
import time
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "log_analyzer"))
try:
    from log_analyzer import analyze_log
    LOG_ANALYZER_MODE = "direct"
except ImportError:
    LOG_ANALYZER_MODE = "http"
    LOG_ANALYZER_URL = os.environ.get("LOG_ANALYZER_URL", "http://localhost:5001")


LOG_DIR = Path(__file__).parent.parent / "logs"
REPORT_DIR = Path(__file__).parent.parent / "reports"
LOG_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

MAX_RETRIES = 2


def run_stage(stage_name: str, simulate_failure: str = None) -> tuple[bool, str]:
    ts = datetime.datetime.utcnow().isoformat()
    log_lines = [f"[{ts}] Starting stage: {stage_name}"]

    time.sleep(0.3) 

    if simulate_failure == stage_name.lower():
        if stage_name == "build":
            log_lines += [
                f"[{ts}] Compiling source files...",
                f"[{ts}] error: compilation failed — Cannot find module 'config'",
                f"[{ts}] BUILD FAILED",
                f"[{ts}] Exit code: 1",
            ]
            return False, "\n".join(log_lines)

        elif stage_name == "test":
            log_lines += [
                f"[{ts}] Running test suite...",
                f"[{ts}] test_auth ... ok",
                f"[{ts}] test_pipeline ... FAIL: test_pipeline",
                f"[{ts}] AssertionError: expected 200, got 500",
                f"[{ts}] 1 failed, 1 passed",
            ]
            return False, "\n".join(log_lines)

        elif stage_name == "deploy":
            log_lines += [
                f"[{ts}] Pulling image pipeline:latest...",
                f"[{ts}] Error response from daemon: port already allocated",
                f"[{ts}] container exited with code 1",
                f"[{ts}] deployment failed",
            ]
            return False, "\n".join(log_lines)

    success_msgs = {
        "build":  "Build completed — 0 errors, 0 warnings.",
        "test":   "Tests passed — 12 passed, 0 failed.",
        "deploy": "Container started successfully on port 8080.",
    }
    log_lines.append(f"[{ts}] {success_msgs.get(stage_name, 'Stage complete.')}")
    return True, "\n".join(log_lines)
