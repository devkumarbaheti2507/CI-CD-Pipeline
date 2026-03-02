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
def call_log_analyzer(log_text: str) -> dict:
    if LOG_ANALYZER_MODE == "direct":
        return analyze_log(log_text)
    else:
        try:
            data = json.dumps({"log": log_text}).encode()
            req = urllib.request.Request(
                f"{LOG_ANALYZER_URL}/analyze",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except Exception as e:
            return {"status": "FAILED", "failure_type": "UNKNOWN", "error": str(e)}




RECOVERY_ACTIONS = {
    "BUILD_ERROR":      "RETRY",
    "TEST_FAILURE":     "RETRY",
    "DEPLOY_ERROR":     "ROLLBACK",
    "DEPENDENCY_ERROR": "RETRY",
    "TIMEOUT":          "RESTART",
    "UNKNOWN":          "RETRY",
}

def determine_recovery(failure_type: str) -> str:
    return RECOVERY_ACTIONS.get(failure_type, "RETRY")

def execute_recovery(action: str, stage: str) -> str:
    ts = datetime.datetime.utcnow().isoformat()
    if action == "RETRY":
        return f"[{ts}] RECOVERY: Retrying stage '{stage}'..."
    elif action == "ROLLBACK":
        return f"[{ts}] RECOVERY: Rolling back to last stable deployment..."
    elif action == "RESTART":
        return f"[{ts}] RECOVERY: Restarting pipeline from scratch..."
    return f"[{ts}] RECOVERY: No action defined for '{action}'."




def run_pipeline(pipeline_id: str, simulate_failure: str = None):
    stages = ["build", "test", "deploy"]
    pipeline_log = []
    report = {
        "pipeline_id": pipeline_id,
        "started_at": datetime.datetime.utcnow().isoformat() + "Z",
        "simulate_failure": simulate_failure,
        "stages": [],
        "final_status": None,
    }

    print(f"\n{'='*60}")
    print(f"  Pipeline ID : {pipeline_id}")
    print(f"  Inject Fault: {simulate_failure or 'None (clean run)'}")
    print(f"{'='*60}")

    for stage in stages:
        stage_result = {
            "stage": stage,
            "attempts": [],
            "outcome": None,
        }
        attempt = 0

        while attempt <= MAX_RETRIES:
            attempt += 1
            print(f"\n[Stage: {stage.upper()}]  Attempt {attempt}/{MAX_RETRIES + 1}")

            success, log_text = run_stage(stage, simulate_failure=simulate_failure)
            pipeline_log.append(log_text)

            # Save log to file
            log_file = LOG_DIR / f"{pipeline_id}_{stage}_attempt{attempt}.log"
            log_file.write_text(log_text)

            if success:
                print(f"  ✓ {stage.capitalize()} PASSED")
                stage_result["attempts"].append({"attempt": attempt, "status": "SUCCESS"})
                stage_result["outcome"] = "SUCCESS"
                # After a successful deploy, clear fault injection
                if stage == simulate_failure:
                    simulate_failure = None
                break
            else:
                print(f"  ✗ {stage.capitalize()} FAILED — sending logs to Log Analyzer...")

                # ── Call Log Analyzer ──
                analysis = call_log_analyzer(log_text)
                failure_type = analysis.get("failure_type", "UNKNOWN")
                print(f"  → Failure Type : {failure_type}")
                print(f"  → Failures Found: {analysis.get('failures_found', '?')}")
                for d in analysis.get("details", []):
                    print(f"     Line {d['line']}: {d['content'][:65]}")

                # ── Recovery Decision ──
                recovery_action = determine_recovery(failure_type)
                recovery_msg = execute_recovery(recovery_action, stage)
                print(f"  → Recovery     : {recovery_action}")
                print(f"  {recovery_msg}")

                stage_result["attempts"].append({
                    "attempt": attempt,
                    "status": "FAILED",
                    "failure_type": failure_type,
                    "recovery_action": recovery_action,
                })

                if recovery_action == "ROLLBACK":
                    stage_result["outcome"] = "ROLLED_BACK"
                    report["stages"].append(stage_result)
                    report["final_status"] = "ROLLED_BACK"
                    _save_report(report, pipeline_id)
                    print(f"\n[Pipeline] Rolled back. Halting pipeline.")
                    return report

                if attempt > MAX_RETRIES:
                    print(f"  Max retries reached for '{stage}'. Aborting pipeline.")
                    stage_result["outcome"] = "FAILED"
                    report["stages"].append(stage_result)
                    report["final_status"] = "FAILED"
                    _save_report(report, pipeline_id)
                    return report

                simulate_failure = None
                time.sleep(0.2)

        report["stages"].append(stage_result)

    report["final_status"] = "SUCCESS"
    _save_report(report, pipeline_id)
    print(f"\n{'='*60}")
    print(f"  Pipeline COMPLETE — Status: {report['final_status']}")
    print(f"{'='*60}\n")
    return report


def _save_report(report: dict, pipeline_id: str):
    report["finished_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    path = REPORT_DIR / f"{pipeline_id}_report.json"
    path.write_text(json.dumps(report, indent=2))
    print(f"\n[Report saved → {path}]")



if __name__ == "__main__":
    scenarios = [
        ("pipeline-001", None),           
        ("pipeline-002", "build"),        
        ("pipeline-003", "test"),         
        ("pipeline-004", "deploy"),       
    ]

    for pid, fault in scenarios:
        run_pipeline(pid, simulate_failure=fault)
        time.sleep(0.5)
