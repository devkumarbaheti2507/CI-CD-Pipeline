"""
╔══════════════════════════════════════════════════════════════════════════════╗
║           CI/CD Pipeline Controller — Production Ready                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Integrates with:                                                           ║
║    • Jenkins  (triggers build/test/deploy jobs via Jenkins REST API)        ║
║    • Log Analyzer  (FastAPI service at LOG_ANALYZER_URL)                   ║
║    • Failure Classifier  (maps analyzer output → recovery strategy)         ║
║    • Recovery Manager  (retry / rollback / restart logic)                   ║
║    • Notification System  (email + webhook alerts)                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  ENVIRONMENT VARIABLES                                                      ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  JENKINS_URL          Jenkins base URL   (default: http://localhost:8080)   ║
║  JENKINS_USER         Jenkins username   (default: admin)                   ║
║  JENKINS_TOKEN        Jenkins API token  (REQUIRED)                         ║
║  JENKINS_JOB_BUILD    Jenkins job name for build   (default: app-build)     ║
║  JENKINS_JOB_TEST     Jenkins job name for test    (default: app-test)      ║
║  JENKINS_JOB_DEPLOY   Jenkins job name for deploy  (default: app-deploy)    ║
║  LOG_ANALYZER_URL     Log Analyzer service URL     (default: http://localhost:5001) ║
║  LOG_ANALYZER_KEY     API key if auth enabled      (default: "")            ║
║  PIPELINE_MAX_RETRIES Max retries per stage        (default: 2)             ║
║  PIPELINE_RETRY_DELAY Seconds between retries      (default: 10)            ║
║  PIPELINE_TIMEOUT     Seconds to wait per job      (default: 1800)          ║
║  PIPELINE_POLL        Jenkins poll interval (s)    (default: 10)            ║
║  NOTIFY_EMAIL_TO      Recipient email(s)  comma-sep (default: "")           ║
║  NOTIFY_SMTP_HOST     SMTP server host             (default: smtp.gmail.com)║
║  NOTIFY_SMTP_PORT     SMTP server port             (default: 587)           ║
║  NOTIFY_SMTP_USER     SMTP username                (default: "")            ║
║  NOTIFY_SMTP_PASS     SMTP password / app-password (default: "")            ║
║  NOTIFY_WEBHOOK_URL   Slack/Teams/generic webhook  (default: "")            ║
║  PIPELINE_REPORT_DIR  Directory for JSON reports   (default: ./reports)     ║
║  LOG_LEVEL            Logging level                (default: INFO)           ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  USAGE                                                                      ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  # Run a full pipeline for a specific git commit                            ║
║  python pipeline_controller.py --commit abc1234 --branch main              ║
║                                                                             ║
║  # Run only specific stages                                                 ║
║  python pipeline_controller.py --commit abc1234 --stages build test        ║
║                                                                             ║
║  # Dry-run (no Jenkins calls, no notifications)                             ║
║  python pipeline_controller.py --commit abc1234 --dry-run                  ║
║                                                                             ║
║  # Expose as HTTP service (webhook receiver for GitHub push events)         ║
║  python pipeline_controller.py --serve                                      ║
║                                                                             ║
║  # Self-test                                                                ║
║  python pipeline_controller.py --test                                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import email.mime.multipart
import email.mime.text
import enum
import http.server
import json
import logging
import os
import pathlib
import signal
import smtplib
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Config:
    # Jenkins
    jenkins_url:        str  = field(default_factory=lambda: os.environ.get("JENKINS_URL",  "http://localhost:8080"))
    jenkins_user:       str  = field(default_factory=lambda: os.environ.get("JENKINS_USER", "admin"))
    jenkins_token:      str  = field(default_factory=lambda: os.environ.get("JENKINS_TOKEN", ""))
    jenkins_job_build:  str  = field(default_factory=lambda: os.environ.get("JENKINS_JOB_BUILD",  "app-build"))
    jenkins_job_test:   str  = field(default_factory=lambda: os.environ.get("JENKINS_JOB_TEST",   "app-test"))
    jenkins_job_deploy: str  = field(default_factory=lambda: os.environ.get("JENKINS_JOB_DEPLOY", "app-deploy"))
    # Log Analyzer
    log_analyzer_url:   str  = field(default_factory=lambda: os.environ.get("LOG_ANALYZER_URL", "http://localhost:5001"))
    log_analyzer_key:   str  = field(default_factory=lambda: os.environ.get("LOG_ANALYZER_KEY", ""))
    # Pipeline behaviour
    max_retries:        int  = field(default_factory=lambda: int(os.environ.get("PIPELINE_MAX_RETRIES", "2")))
    retry_delay:        int  = field(default_factory=lambda: int(os.environ.get("PIPELINE_RETRY_DELAY", "10")))
    job_timeout:        int  = field(default_factory=lambda: int(os.environ.get("PIPELINE_TIMEOUT",     "1800")))
    poll_interval:      int  = field(default_factory=lambda: int(os.environ.get("PIPELINE_POLL",        "10")))
    # Notifications
    notify_email_to:    str  = field(default_factory=lambda: os.environ.get("NOTIFY_EMAIL_TO",    ""))
    notify_smtp_host:   str  = field(default_factory=lambda: os.environ.get("NOTIFY_SMTP_HOST",   "smtp.gmail.com"))
    notify_smtp_port:   int  = field(default_factory=lambda: int(os.environ.get("NOTIFY_SMTP_PORT", "587")))
    notify_smtp_user:   str  = field(default_factory=lambda: os.environ.get("NOTIFY_SMTP_USER",   ""))
    notify_smtp_pass:   str  = field(default_factory=lambda: os.environ.get("NOTIFY_SMTP_PASS",   ""))
    notify_webhook_url: str  = field(default_factory=lambda: os.environ.get("NOTIFY_WEBHOOK_URL", ""))
    # Storage
    report_dir:         str  = field(default_factory=lambda: os.environ.get("PIPELINE_REPORT_DIR", "./reports"))
    log_level:          str  = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").upper())
    version:            str  = "2.0.0"
    service_name:       str  = "pipeline-controller"


CFG = Config()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2 — STRUCTURED LOGGER
# ═════════════════════════════════════════════════════════════════════════════

class _Logger:
    _COLOURS = {
        "DEBUG": "\033[36m", "INFO": "\033[32m",
        "WARNING": "\033[33m", "ERROR": "\033[31m",
        "CRITICAL": "\033[35m", "RESET": "\033[0m",
    }

    def __init__(self, name: str, level: str):
        self._name = name
        root = logging.getLogger(name)
        root.setLevel(getattr(logging, level, logging.INFO))
        if not root.handlers:
            h = logging.StreamHandler(sys.stderr)
            h.setFormatter(logging.Formatter("%(message)s"))
            root.addHandler(h)
        self._log = root

    def _emit(self, level: str, msg: str, **kw):
        ts  = datetime.now(timezone.utc).isoformat()
        col = self._COLOURS.get(level, "")
        rst = self._COLOURS["RESET"]
        ext = "  " + "  ".join(f"{k}={v}" for k, v in kw.items()) if kw else ""
        line = f"{col}[{ts}] {level:<8} {self._name}: {msg}{ext}{rst}"
        getattr(self._log, level.lower(), self._log.info)(line)

    def debug(self, m, **k):    self._emit("DEBUG",    m, **k)
    def info(self, m, **k):     self._emit("INFO",     m, **k)
    def warning(self, m, **k):  self._emit("WARNING",  m, **k)
    def error(self, m, **k):    self._emit("ERROR",    m, **k)
    def critical(self, m, **k): self._emit("CRITICAL", m, **k)


log = _Logger(CFG.service_name, CFG.log_level)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3 — DOMAIN MODELS
# ═════════════════════════════════════════════════════════════════════════════

class StageStatus(str, enum.Enum):
    PENDING     = "PENDING"
    RUNNING     = "RUNNING"
    SUCCESS     = "SUCCESS"
    FAILED      = "FAILED"
    RETRYING    = "RETRYING"
    ROLLED_BACK = "ROLLED_BACK"
    SKIPPED     = "SKIPPED"


class RecoveryAction(str, enum.Enum):
    RETRY    = "RETRY"
    ROLLBACK = "ROLLBACK"
    RESTART  = "RESTART"
    ABORT    = "ABORT"
    NONE     = "NONE"


@dataclass
class StageAttempt:
    attempt:         int
    status:          StageStatus
    jenkins_build_no: Optional[int]   = None
    log_url:         Optional[str]    = None
    raw_log:         Optional[str]    = None
    analysis:        Optional[Dict]   = None
    recovery_action: RecoveryAction   = RecoveryAction.NONE
    started_at:      Optional[str]    = None
    finished_at:     Optional[str]    = None
    duration_s:      float            = 0.0
    error:           Optional[str]    = None


@dataclass
class StageResult:
    name:        str
    job:         str
    status:      StageStatus        = StageStatus.PENDING
    attempts:    List[StageAttempt] = field(default_factory=list)
    started_at:  Optional[str]      = None
    finished_at: Optional[str]      = None

    @property
    def total_attempts(self) -> int:
        return len(self.attempts)

    @property
    def last_attempt(self) -> Optional[StageAttempt]:
        return self.attempts[-1] if self.attempts else None


@dataclass
class PipelineRun:
    pipeline_id:  str
    commit_sha:   str
    branch:       str
    stages:       List[StageResult]  = field(default_factory=list)
    final_status: StageStatus        = StageStatus.PENDING
    started_at:   Optional[str]      = None
    finished_at:  Optional[str]      = None
    triggered_by: str                = "cli"
    dry_run:      bool               = False

    def to_dict(self) -> Dict:
        return dataclasses.asdict(self)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 4 — HTTP CLIENT  (shared, with retry + timeout)
# ═════════════════════════════════════════════════════════════════════════════

class HttpClient:
    """
    Thin wrapper around urllib with:
      - configurable timeout
      - automatic JSON encode/decode
      - retry on transient errors (5xx, connection errors)
      - optional Basic Auth header
    """

    def __init__(
        self,
        base_url:   str,
        timeout:    int             = 30,
        auth:       Optional[Tuple] = None,   # (user, token)
        extra_headers: Dict         = None,
        retries:    int             = 3,
        backoff:    float           = 2.0,
    ):
        self._base     = base_url.rstrip("/")
        self._timeout  = timeout
        self._retries  = retries
        self._backoff  = backoff
        self._headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
        if auth:
            creds = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
            self._headers["Authorization"] = f"Basic {creds}"
        if extra_headers:
            self._headers.update(extra_headers)

    def _request(
        self,
        method:  str,
        path:    str,
        body:    Optional[Dict] = None,
        headers: Optional[Dict] = None,
        raw_response: bool      = False,
    ) -> Any:
        url   = self._base + path
        data  = json.dumps(body).encode() if body else None
        hdrs  = {**self._headers, **(headers or {})}

        last_err: Optional[Exception] = None
        for attempt in range(1, self._retries + 1):
            try:
                req  = urllib.request.Request(url, data=data, headers=hdrs, method=method)
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    raw = resp.read()
                    if raw_response:
                        return raw.decode(errors="replace")
                    ct = resp.headers.get("Content-Type", "")
                    if "application/json" in ct or raw.startswith(b"{") or raw.startswith(b"["):
                        return json.loads(raw)
                    return raw.decode(errors="replace")

            except urllib.error.HTTPError as e:
                body_txt = e.read().decode(errors="replace")
                if e.code < 500:
                    raise RuntimeError(f"HTTP {e.code} {e.reason}: {body_txt}") from e
                last_err = RuntimeError(f"HTTP {e.code} {e.reason}: {body_txt}")
            except (urllib.error.URLError, OSError, socket.timeout) as e:
                last_err = e

            if attempt < self._retries:
                wait = self._backoff ** attempt
                log.warning("HTTP retry", attempt=attempt, url=url, error=str(last_err), wait_s=wait)
                time.sleep(wait)

        raise ConnectionError(f"Request failed after {self._retries} attempts: {last_err}") from last_err

    def get(self, path: str, **kw):               return self._request("GET",    path, **kw)
    def post(self, path: str, body: Dict, **kw):  return self._request("POST",   path, body=body, **kw)
    def get_text(self, path: str):                return self._request("GET",    path, raw_response=True)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 5 — JENKINS CLIENT
# ═════════════════════════════════════════════════════════════════════════════

class JenkinsBuildStatus(str, enum.Enum):
    SUCCESS  = "SUCCESS"
    FAILURE  = "FAILURE"
    UNSTABLE = "UNSTABLE"
    ABORTED  = "ABORTED"
    RUNNING  = None   # type: ignore


class JenkinsClient:
    """
    Wraps Jenkins REST API.
    Supports: trigger job, poll for completion, fetch console log.
    """

    def __init__(self, cfg: Config):
        self._cfg    = cfg
        self._http   = HttpClient(
            base_url = cfg.jenkins_url,
            timeout  = 30,
            auth     = (cfg.jenkins_user, cfg.jenkins_token),
            retries  = 3,
        )

    # ── trigger ───────────────────────────────────────────
    def trigger(self, job: str, params: Dict) -> int:
        """
        Trigger a parameterised Jenkins job.
        Returns the queue item number (used to resolve build number).
        """
        qs  = urllib.parse.urlencode(params)
        path = f"/job/{urllib.parse.quote(job)}/buildWithParameters?{qs}"
        try:
            req = urllib.request.Request(
                self._cfg.jenkins_url + path,
                data    = b"",
                headers = {
                    "Authorization": self._http._headers["Authorization"],
                    "Content-Type":  "application/x-www-form-urlencoded",
                },
                method  = "POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                location = resp.headers.get("Location", "")
                # Location: http://jenkins/queue/item/42/
                match = [s for s in location.split("/") if s.isdigit()]
                queue_no = int(match[-1]) if match else 0
                log.info("Job triggered", job=job, queue_item=queue_no)
                return queue_no
        except Exception as exc:
            raise RuntimeError(f"Failed to trigger Jenkins job '{job}': {exc}") from exc

    def _queue_item_to_build(self, queue_no: int, timeout: int = 60) -> int:
        """Poll the queue item until the build number is assigned."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data = self._http.get(f"/queue/item/{queue_no}/api/json")
                exe  = data.get("executable")
                if exe and exe.get("number"):
                    return int(exe["number"])
            except Exception:
                pass
            time.sleep(3)
        raise TimeoutError(f"Queue item {queue_no} did not start within {timeout}s")

    # ── poll ──────────────────────────────────────────────
    def wait_for_build(
        self,
        job:          str,
        queue_no:     int,
        timeout:      int,
        poll_interval: int,
        on_poll:      Optional[Callable] = None,
    ) -> Tuple[str, int, str]:
        """
        Block until the build finishes (or timeout).
        Returns (result, build_number, log_url).
        """
        build_no = self._queue_item_to_build(queue_no)
        log.info("Build started", job=job, build=build_no)
        job_path  = f"/job/{urllib.parse.quote(job)}/{build_no}"
        log_url   = f"{self._cfg.jenkins_url}{job_path}/console"
        deadline  = time.monotonic() + timeout

        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            try:
                data   = self._http.get(f"{job_path}/api/json")
                result = data.get("result")          # None = still running
                if result is not None:
                    log.info("Build finished", job=job, build=build_no, result=result)
                    return result, build_no, log_url
                if on_poll:
                    on_poll(job=job, build=build_no)
            except Exception as exc:
                log.warning("Poll error", job=job, build=build_no, error=str(exc))

        # timeout — abort the build
        try:
            self._http.post(
                f"/job/{urllib.parse.quote(job)}/{build_no}/stop",
                body={},
            )
        except Exception:
            pass
        raise TimeoutError(f"Job '{job}' build #{build_no} exceeded {timeout}s timeout")

    # ── console log ───────────────────────────────────────
    def get_console_log(self, job: str, build_no: int) -> str:
        """Fetch the full console output for a build."""
        try:
            return self._http.get_text(
                f"/job/{urllib.parse.quote(job)}/{build_no}/consoleText"
            )
        except Exception as exc:
            log.warning("Could not fetch console log", job=job, build=build_no, error=str(exc))
            return f"[Console log unavailable: {exc}]"

    def get_last_stable_build(self, job: str) -> Optional[int]:
        """Return the build number of the last successful build (for rollback)."""
        try:
            data = self._http.get(f"/job/{urllib.parse.quote(job)}/lastStableBuild/api/json")
            return data.get("number")
        except Exception:
            return None

    def redeploy_build(self, job: str, build_no: int, params: Dict) -> int:
        """Re-trigger the deploy job pinned to a specific build artifact."""
        params["ROLLBACK_BUILD"] = str(build_no)
        return self.trigger(job, params)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 6 — LOG ANALYZER CLIENT
# ═════════════════════════════════════════════════════════════════════════════

class LogAnalyzerClient:
    """
    Client for the FastAPI Log Analyzer service.
    Matches the API exposed by log_analyzer.py:
      GET  /health
      POST /analyze    { "log": "<text>" }
      GET  /analyze-file?path=<path>
    """

    def __init__(self, cfg: Config):
        headers = {}
        if cfg.log_analyzer_key:
            headers["X-API-Key"] = cfg.log_analyzer_key
        self._http = HttpClient(
            base_url      = cfg.log_analyzer_url,
            timeout        = 60,
            extra_headers  = headers,
            retries        = 3,
        )
        self._available: Optional[bool] = None

    def check_health(self) -> bool:
        """Return True if the Log Analyzer service is reachable."""
        try:
            resp = self._http.get("/health")
            ok   = isinstance(resp, dict) and resp.get("status") == "ok"
            self._available = ok
            return ok
        except Exception as exc:
            log.warning("Log Analyzer health check failed", error=str(exc))
            self._available = False
            return False

    def analyze(self, log_text: str) -> Dict:
        """
        Send log text to POST /analyze.
        Returns the analysis dict from the service.
        Falls back to a minimal local result if service is unreachable.
        """
        try:
            result = self._http.post("/analyze", body={"log": log_text})
            log.debug(
                "Log analyzed",
                status          = result.get("status"),
                failure_type    = result.get("failure_type"),
                failures_found  = result.get("failures_found"),
            )
            return result
        except Exception as exc:
            log.error("Log Analyzer call failed — using fallback", error=str(exc))
            return self._fallback_analyze(log_text, str(exc))

    def analyze_file(self, path: str) -> Dict:
        """Call GET /analyze-file?path=<path>."""
        try:
            return self._http.get(f"/analyze-file?path={urllib.parse.quote(path)}")
        except Exception as exc:
            log.error("Log Analyzer file analysis failed", path=path, error=str(exc))
            return self._fallback_analyze(pathlib.Path(path).read_text(errors="replace"))

    # ── fallback: minimal regex scan when service is down ─
    _FALLBACK_PATTERNS = {
        "BUILD_ERROR":     [r"BUILD FAILED", r"compilation failed", r"Cannot find module"],
        "TEST_FAILURE":    [r"FAILED\s+tests/", r"\d+ failed", r"AssertionError"],
        "DEPLOY_ERROR":    [r"deployment failed", r"Error response from daemon",
                            r"container exited with code [^0]"],
        "DEPENDENCY_ERROR":[r"npm ERR!", r"pip.*ERROR", r"Could not resolve"],
        "TIMEOUT":         [r"timeout exceeded", r"Timed out", r"ETIMEDOUT"],
    }

    def _fallback_analyze(self, log_text: str, svc_error: str = "") -> Dict:
        import re
        lines    = log_text.splitlines()
        detected = []
        for ln, line in enumerate(lines, 1):
            for ft, patterns in self._FALLBACK_PATTERNS.items():
                for p in patterns:
                    if re.search(p, line, re.IGNORECASE):
                        detected.append({"line": ln, "content": line.strip(), "failure_type": ft})
                        break
        seen, unique = set(), []
        for d in detected:
            if d["line"] not in seen:
                seen.add(d["line"])
                unique.append(d)
        priority   = ["DEPLOY_ERROR", "BUILD_ERROR", "TEST_FAILURE", "DEPENDENCY_ERROR", "TIMEOUT"]
        found_types = {d["failure_type"] for d in unique}
        ft         = next((t for t in priority if t in found_types), None) if unique else None
        return {
            "status":        "FAILED" if unique else "SUCCESS",
            "failure_type":  ft,
            "total_lines":   len(lines),
            "failures_found": len(unique),
            "details":       unique,
            "timestamp":     datetime.now(timezone.utc).isoformat() + "Z",
            "_fallback":     True,
            "_svc_error":    svc_error,
        }


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 7 — FAILURE CLASSIFIER
# ═════════════════════════════════════════════════════════════════════════════

class FailureClassifier:
    """
    Maps Log Analyzer output → RecoveryAction.

    Classification table:
    ┌──────────────────────┬────────────┬──────────────────────────────────────┐
    │ failure_type         │ stage      │ action                               │
    ├──────────────────────┼────────────┼──────────────────────────────────────┤
    │ BUILD_ERROR          │ any        │ RETRY  (up to max_retries)           │
    │ DEPENDENCY_ERROR     │ any        │ RETRY                                │
    │ TEST_FAILURE         │ test       │ RETRY                                │
    │ DEPLOY_ERROR         │ deploy     │ ROLLBACK → re-deploy last stable     │
    │ TIMEOUT              │ any        │ RESTART (retry from that stage)      │
    │ None / SUCCESS       │ any        │ NONE                                 │
    │ (unknown)            │ any        │ ABORT                                │
    └──────────────────────┴────────────┴──────────────────────────────────────┘
    """

    _TABLE: Dict[str, RecoveryAction] = {
        "BUILD_ERROR":      RecoveryAction.RETRY,
        "DEPENDENCY_ERROR": RecoveryAction.RETRY,
        "TEST_FAILURE":     RecoveryAction.RETRY,
        "DEPLOY_ERROR":     RecoveryAction.ROLLBACK,
        "TIMEOUT":          RecoveryAction.RESTART,
    }

    def classify(self, analysis: Dict, stage_name: str) -> RecoveryAction:
        if analysis.get("status") == "SUCCESS" or not analysis.get("failure_type"):
            return RecoveryAction.NONE
        action = self._TABLE.get(analysis["failure_type"], RecoveryAction.ABORT)
        log.info(
            "Failure classified",
            stage        = stage_name,
            failure_type = analysis.get("failure_type"),
            action       = action.value,
            failures     = analysis.get("failures_found"),
        )
        return action

    def top_findings(self, analysis: Dict, n: int = 5) -> List[Dict]:
        return (analysis.get("details") or [])[:n]


CLASSIFIER = FailureClassifier()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 8 — RECOVERY MANAGER
# ═════════════════════════════════════════════════════════════════════════════

class RecoveryManager:
    """
    Executes recovery actions.
    Works alongside Jenkins: for ROLLBACK it re-triggers the deploy job
    pointing at the last stable build artifact.
    """

    def __init__(self, jenkins: JenkinsClient, cfg: Config):
        self._jenkins = jenkins
        self._cfg     = cfg

    def execute(
        self,
        action:    RecoveryAction,
        stage:     StageResult,
        run:       PipelineRun,
        attempt:   StageAttempt,
        delay:     int,
    ) -> str:
        """
        Execute the recovery action. Returns a human-readable description.
        """
        ts = datetime.now(timezone.utc).isoformat()

        if action == RecoveryAction.RETRY:
            msg = f"[{ts}] RECOVERY: Retrying stage '{stage.name}' in {delay}s..."
            log.info("Recovery: RETRY", stage=stage.name, delay_s=delay)
            time.sleep(delay)
            return msg

        if action == RecoveryAction.RESTART:
            msg = f"[{ts}] RECOVERY: Restarting stage '{stage.name}' (TIMEOUT recovery) in {delay}s..."
            log.info("Recovery: RESTART", stage=stage.name, delay_s=delay)
            time.sleep(delay)
            return msg

        if action == RecoveryAction.ROLLBACK:
            log.info("Recovery: ROLLBACK", stage=stage.name)
            stable_build = self._jenkins.get_last_stable_build(stage.job)
            if stable_build:
                log.info("Rolling back to stable build", build=stable_build, job=stage.job)
                params = {"GIT_COMMIT": run.commit_sha, "BRANCH": run.branch}
                try:
                    queue_no = self._jenkins.redeploy_build(stage.job, stable_build, params)
                    msg = (
                        f"[{ts}] RECOVERY: Rolled back deploy to build #{stable_build}. "
                        f"Queue item: {queue_no}"
                    )
                except Exception as exc:
                    msg = f"[{ts}] RECOVERY: Rollback trigger failed: {exc}"
            else:
                msg = f"[{ts}] RECOVERY: No stable build found. Manual intervention required."
            log.info("Rollback complete", message=msg)
            return msg

        if action == RecoveryAction.ABORT:
            msg = f"[{ts}] RECOVERY: Unrecoverable failure in '{stage.name}'. Aborting pipeline."
            log.error("Recovery: ABORT", stage=stage.name)
            return msg

        return f"[{ts}] RECOVERY: No action for '{action.value}'"


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 9 — NOTIFICATION SYSTEM
# ═════════════════════════════════════════════════════════════════════════════

class NotificationSystem:
    """
    Sends alerts via:
      • Email (SMTP / TLS)
      • Webhook (Slack / Teams / generic HTTP POST)
    """

    def __init__(self, cfg: Config):
        self._cfg = cfg

    def notify(self, run: PipelineRun, stage: Optional[StageResult] = None) -> None:
        """Send notifications in background threads so they don't block the pipeline."""
        subject, body, webhook_payload = self._build_payloads(run, stage)
        threads = []
        if self._cfg.notify_email_to and self._cfg.notify_smtp_user:
            t = threading.Thread(
                target=self._send_email, args=(subject, body), daemon=True
            )
            t.start(); threads.append(t)
        if self._cfg.notify_webhook_url:
            t = threading.Thread(
                target=self._send_webhook, args=(webhook_payload,), daemon=True
            )
            t.start(); threads.append(t)
        # wait up to 10s for notification delivery
        for t in threads:
            t.join(timeout=10)

    def _build_payloads(
        self, run: PipelineRun, stage: Optional[StageResult]
    ) -> Tuple[str, str, Dict]:
        status  = run.final_status.value
        icon    = "✅" if status == "SUCCESS" else "❌"
        subject = f"{icon} Pipeline {run.pipeline_id} — {status} [{run.branch}@{run.commit_sha[:8]}]"

        lines = [
            f"Pipeline ID  : {run.pipeline_id}",
            f"Commit       : {run.commit_sha}",
            f"Branch       : {run.branch}",
            f"Status       : {status}",
            f"Started      : {run.started_at}",
            f"Finished     : {run.finished_at}",
            "",
        ]
        for sr in run.stages:
            lines.append(f"  [{sr.status.value:<12}] {sr.name.upper()}")
            for att in sr.attempts:
                a = att.analysis or {}
                lines.append(
                    f"    Attempt {att.attempt}: {att.status.value}"
                    + (f" | Failure: {a.get('failure_type', '-')}"
                       if att.status == StageStatus.FAILED else "")
                    + (f" | Recovery: {att.recovery_action.value}"
                       if att.recovery_action != RecoveryAction.NONE else "")
                )
                for finding in (a.get("details") or [])[:3]:
                    lines.append(f"      Line {finding['line']}: {finding['content'][:80]}")

        body = "\n".join(lines)
        webhook_payload = {
            "text":        subject,
            "pipeline_id": run.pipeline_id,
            "commit":      run.commit_sha,
            "branch":      run.branch,
            "status":      status,
            "details":     body,
        }
        return subject, body, webhook_payload

    def _send_email(self, subject: str, body: str) -> None:
        try:
            msg              = email.mime.multipart.MIMEMultipart()
            msg["From"]      = self._cfg.notify_smtp_user
            msg["To"]        = self._cfg.notify_email_to
            msg["Subject"]   = subject
            msg.attach(email.mime.text.MIMEText(body, "plain"))
            with smtplib.SMTP(self._cfg.notify_smtp_host, self._cfg.notify_smtp_port) as s:
                s.ehlo()
                s.starttls()
                s.login(self._cfg.notify_smtp_user, self._cfg.notify_smtp_pass)
                s.send_message(msg)
            log.info("Email notification sent", to=self._cfg.notify_email_to)
        except Exception as exc:
            log.error("Email notification failed", error=str(exc))

    def _send_webhook(self, payload: Dict) -> None:
        try:
            data = json.dumps(payload).encode()
            req  = urllib.request.Request(
                self._cfg.notify_webhook_url,
                data    = data,
                headers = {"Content-Type": "application/json"},
                method  = "POST",
            )
            with urllib.request.urlopen(req, timeout=10):
                pass
            log.info("Webhook notification sent", url=self._cfg.notify_webhook_url)
        except Exception as exc:
            log.error("Webhook notification failed", error=str(exc))


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 10 — REPORT WRITER
# ═════════════════════════════════════════════════════════════════════════════

class ReportWriter:
    """Persists pipeline run results as JSON files."""

    def __init__(self, cfg: Config):
        self._dir = pathlib.Path(cfg.report_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, run: PipelineRun) -> pathlib.Path:
        path = self._dir / f"{run.pipeline_id}_report.json"
        path.write_text(json.dumps(run.to_dict(), indent=2, default=str))
        log.info("Report saved", path=str(path))
        return path

    def load(self, pipeline_id: str) -> Optional[Dict]:
        path = self._dir / f"{pipeline_id}_report.json"
        if path.exists():
            return json.loads(path.read_text())
        return None


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 11 — PIPELINE CONTROLLER  (core orchestrator)
# ═════════════════════════════════════════════════════════════════════════════

class PipelineController:
    """
    Orchestrates: Build → Test → Deploy
    On each stage failure:
      1. Fetch Jenkins console log
      2. Send to Log Analyzer  → get structured analysis
      3. Pass to Failure Classifier  → get recovery action
      4. Execute via Recovery Manager  → retry / rollback / abort
      5. Send notifications
      6. Save report
    """

    _STAGES = [
        ("build",  "jenkins_job_build"),
        ("test",   "jenkins_job_test"),
        ("deploy", "jenkins_job_deploy"),
    ]

    def __init__(self, cfg: Config = CFG, dry_run: bool = False):
        self._cfg      = cfg
        self._dry_run  = dry_run
        self._jenkins  = JenkinsClient(cfg)
        self._analyzer = LogAnalyzerClient(cfg)
        self._recovery = RecoveryManager(self._jenkins, cfg)
        self._notifier = NotificationSystem(cfg)
        self._reporter = ReportWriter(cfg)

    # ─────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────

    def run(
        self,
        commit_sha:   str,
        branch:       str       = "main",
        stages:       Optional[List[str]] = None,
        triggered_by: str       = "cli",
    ) -> PipelineRun:
        """Execute the full (or partial) pipeline and return the PipelineRun."""
        pipeline_id = f"pipeline-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:6]}"
        log.info("Pipeline starting", pipeline_id=pipeline_id, commit=commit_sha, branch=branch)

        run = PipelineRun(
            pipeline_id  = pipeline_id,
            commit_sha   = commit_sha,
            branch       = branch,
            started_at   = datetime.now(timezone.utc).isoformat(),
            triggered_by = triggered_by,
            dry_run      = self._dry_run,
        )

        active_stages = stages or [s[0] for s in self._STAGES]
        self._print_banner(run)

        # ── verify Log Analyzer is reachable ──────────────
        if not self._dry_run:
            if not self._analyzer.check_health():
                log.warning(
                    "Log Analyzer unreachable — will use fallback classifier",
                    url=self._cfg.log_analyzer_url
                )

        # ── execute each stage ────────────────────────────
        for stage_name, job_attr in self._STAGES:
            if stage_name not in active_stages:
                continue

            job_name = getattr(self._cfg, job_attr)
            stage    = StageResult(name=stage_name, job=job_name,
                                   started_at=datetime.now(timezone.utc).isoformat())
            run.stages.append(stage)

            outcome = self._run_stage(stage, run)

            if outcome in (StageStatus.FAILED, StageStatus.ROLLED_BACK):
                run.final_status  = outcome
                run.finished_at   = datetime.now(timezone.utc).isoformat()
                self._reporter.save(run)
                self._notifier.notify(run, stage)
                self._print_summary(run)
                return run

        run.final_status = StageStatus.SUCCESS
        run.finished_at  = datetime.now(timezone.utc).isoformat()
        self._reporter.save(run)
        self._notifier.notify(run)
        self._print_summary(run)
        return run

    # ─────────────────────────────────────────────────────
    # Stage execution with retry loop
    # ─────────────────────────────────────────────────────

    def _run_stage(self, stage: StageResult, run: PipelineRun) -> StageStatus:
        attempt_no = 0

        while attempt_no <= self._cfg.max_retries:
            attempt_no += 1
            t0          = time.monotonic()
            attempt     = StageAttempt(
                attempt    = attempt_no,
                status     = StageStatus.RUNNING,
                started_at = datetime.now(timezone.utc).isoformat(),
            )
            stage.attempts.append(attempt)
            stage.status = StageStatus.RUNNING

            print(f"\n  [Stage: {stage.name.upper()}]  Attempt {attempt_no}/{self._cfg.max_retries + 1}")

            # ── trigger Jenkins job ────────────────────────
            params = {"GIT_COMMIT": run.commit_sha, "BRANCH": run.branch}
            try:
                result, build_no, log_url = self._trigger_and_wait(stage, params, attempt)
            except Exception as exc:
                attempt.error       = str(exc)
                attempt.status      = StageStatus.FAILED
                attempt.finished_at = datetime.now(timezone.utc).isoformat()
                attempt.duration_s  = round(time.monotonic() - t0, 2)
                log.error("Stage exception", stage=stage.name, attempt=attempt_no, error=str(exc))
                result, build_no, log_url = "FAILURE", None, None

            attempt.jenkins_build_no = build_no
            attempt.log_url          = log_url
            attempt.duration_s       = round(time.monotonic() - t0, 2)

            # ── SUCCESS ────────────────────────────────────
            if result == "SUCCESS":
                attempt.status  = StageStatus.SUCCESS
                stage.status    = StageStatus.SUCCESS
                stage.finished_at = datetime.now(timezone.utc).isoformat()
                print(f"    ✓ {stage.name.capitalize()} PASSED  "
                      f"(build #{build_no}, {attempt.duration_s}s)")
                return StageStatus.SUCCESS

            # ── FAILURE — fetch log and analyze ───────────
            print(f"    ✗ {stage.name.capitalize()} FAILED  "
                  f"(build #{build_no}, result={result})")
            attempt.status = StageStatus.FAILED

            raw_log = ""
            if build_no and not self._dry_run:
                raw_log = self._jenkins.get_console_log(stage.job, build_no)
                attempt.raw_log = raw_log[:4096]   # store first 4KB in report

            analysis = self._analyze_log(raw_log, run.pipeline_id, attempt_no)
            attempt.analysis = analysis

            action = CLASSIFIER.classify(analysis, stage.name)
            attempt.recovery_action = action

            self._print_finding_summary(analysis)

            # ── ABORT — unrecoverable ──────────────────────
            if action == RecoveryAction.ABORT:
                stage.status      = StageStatus.FAILED
                stage.finished_at = datetime.now(timezone.utc).isoformat()
                self._recovery.execute(action, stage, run, attempt, 0)
                return StageStatus.FAILED

            # ── ROLLBACK ───────────────────────────────────
            if action == RecoveryAction.ROLLBACK:
                msg = self._recovery.execute(action, stage, run, attempt, 0)
                print(f"    → {msg}")
                stage.status      = StageStatus.ROLLED_BACK
                stage.finished_at = datetime.now(timezone.utc).isoformat()
                return StageStatus.ROLLED_BACK

            # ── RETRY / RESTART ────────────────────────────
            if attempt_no > self._cfg.max_retries:
                log.error("Max retries exceeded", stage=stage.name, attempts=attempt_no)
                stage.status      = StageStatus.FAILED
                stage.finished_at = datetime.now(timezone.utc).isoformat()
                return StageStatus.FAILED

            msg = self._recovery.execute(
                action, stage, run, attempt, self._cfg.retry_delay
            )
            print(f"    → {msg}")
            stage.status = StageStatus.RETRYING

        stage.status      = StageStatus.FAILED
        stage.finished_at = datetime.now(timezone.utc).isoformat()
        return StageStatus.FAILED

    # ─────────────────────────────────────────────────────
    # Jenkins trigger + wait  (or dry-run simulation)
    # ─────────────────────────────────────────────────────

    def _trigger_and_wait(
        self,
        stage:   StageResult,
        params:  Dict,
        attempt: StageAttempt,
    ) -> Tuple[str, Optional[int], Optional[str]]:
        if self._dry_run:
            log.info("DRY-RUN: skipping Jenkins trigger", stage=stage.name)
            time.sleep(0.3)
            return "SUCCESS", None, None

        queue_no = self._jenkins.trigger(stage.job, params)
        result, build_no, log_url = self._jenkins.wait_for_build(
            job           = stage.job,
            queue_no      = queue_no,
            timeout       = self._cfg.job_timeout,
            poll_interval = self._cfg.poll_interval,
            on_poll       = lambda **kw: log.debug("Job running...", **kw),
        )
        return result, build_no, log_url

    # ─────────────────────────────────────────────────────
    # Log analysis (via service or fallback)
    # ─────────────────────────────────────────────────────

    def _analyze_log(self, raw_log: str, pipeline_id: str, attempt: int) -> Dict:
        print(f"    → Sending logs to Log Analyzer ({self._cfg.log_analyzer_url})...")
        analysis = self._analyzer.analyze(raw_log)
        return analysis

    # ─────────────────────────────────────────────────────
    # Display helpers
    # ─────────────────────────────────────────────────────

    @staticmethod
    def _print_banner(run: PipelineRun) -> None:
        print("\n" + "=" * 64)
        print(f"  CI/CD Pipeline Controller  v{CFG.version}")
        print(f"  Pipeline ID : {run.pipeline_id}")
        print(f"  Commit      : {run.commit_sha}")
        print(f"  Branch      : {run.branch}")
        print(f"  Dry-run     : {run.dry_run}")
        print("=" * 64)

    @staticmethod
    def _print_finding_summary(analysis: Dict) -> None:
        ft  = analysis.get("failure_type",  "—")
        cnt = analysis.get("failures_found", 0)
        fb  = " [FALLBACK]" if analysis.get("_fallback") else ""
        print(f"    → Failure Type    : {ft}{fb}")
        print(f"    → Failures Found  : {cnt}")
        for d in (analysis.get("details") or [])[:4]:
            print(f"       Line {d['line']:>4}: {d['content'][:70]}")

    @staticmethod
    def _print_summary(run: PipelineRun) -> None:
        sym = "✓" if run.final_status == StageStatus.SUCCESS else "✗"
        print("\n" + "=" * 64)
        print(f"  {sym}  Pipeline {run.final_status.value}")
        print(f"     ID      : {run.pipeline_id}")
        for sr in run.stages:
            attempts_str = f"({sr.total_attempts} attempt{'s' if sr.total_attempts != 1 else ''})"
            print(f"     {sr.name.upper():<8}: {sr.status.value}  {attempts_str}")
        print("=" * 64 + "\n")


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 12 — WEBHOOK SERVER  (GitHub push → auto-trigger)
# ═════════════════════════════════════════════════════════════════════════════

class WebhookHandler(http.server.BaseHTTPRequestHandler):
    """
    Minimal GitHub webhook receiver.
    Listens for push events and triggers the pipeline in a background thread.
    POST /webhook  — GitHub push payload
    GET  /health   — liveness
    """

    controller: PipelineController = None   # injected before server starts

    def log_message(self, fmt, *args):
        pass  # silenced — we use structured logger

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"status": "ok", "service": CFG.service_name})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/webhook":
            self._respond(404, {"error": "not found"})
            return
        try:
            length  = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length))
        except Exception as exc:
            self._respond(400, {"error": f"invalid payload: {exc}"})
            return

        event   = self.headers.get("X-GitHub-Event", "")
        if event not in ("push", ""):
            self._respond(200, {"ignored": True, "reason": f"event={event}"})
            return

        commit_sha = (
            payload.get("after")
            or payload.get("head_commit", {}).get("id", "unknown")
        )
        branch = payload.get("ref", "refs/heads/main").replace("refs/heads/", "")

        log.info("Webhook received", event=event, commit=commit_sha, branch=branch)
        self._respond(202, {"accepted": True, "commit": commit_sha, "branch": branch})

        # run pipeline asynchronously so webhook returns immediately
        threading.Thread(
            target=self.controller.run,
            kwargs=dict(commit_sha=commit_sha, branch=branch, triggered_by="webhook"),
            daemon=True,
        ).start()

    def _respond(self, status: int, body: Dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_webhook_server(host: str = "0.0.0.0", port: int = 9000) -> None:
    controller = PipelineController()
    WebhookHandler.controller = controller
    server = http.server.HTTPServer((host, port), WebhookHandler)
    log.info("Webhook server started", host=host, port=port, endpoint="/webhook")
    print(f"\n  Webhook receiver →  http://{host}:{port}/webhook\n")
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: (server.shutdown(), sys.exit(0)))
    server.serve_forever()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 13 — SELF-TEST SUITE
# ═════════════════════════════════════════════════════════════════════════════

def run_self_tests() -> bool:
    passed = failed = 0
    errs: List[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  ✓  {name}")
        else:
            failed += 1
            errs.append(name)
            print(f"  ✗  {name}  {detail}")

    print("\n" + "═" * 60)
    print("  Pipeline Controller — Self-Test Suite")
    print("═" * 60)

    # ── Config ────────────────────────────────────────────
    print("\n[Config]")
    check("host default",       CFG.jenkins_url.startswith("http"))
    check("max_retries >= 1",   CFG.max_retries >= 1)
    check("job_timeout >= 60",  CFG.job_timeout >= 60)

    # ── Failure Classifier ────────────────────────────────
    print("\n[FailureClassifier]")
    clf = FailureClassifier()
    check("BUILD_ERROR → RETRY",
          clf.classify({"status": "FAILED", "failure_type": "BUILD_ERROR"}, "build") == RecoveryAction.RETRY)
    check("TEST_FAILURE → RETRY",
          clf.classify({"status": "FAILED", "failure_type": "TEST_FAILURE"}, "test") == RecoveryAction.RETRY)
    check("DEPLOY_ERROR → ROLLBACK",
          clf.classify({"status": "FAILED", "failure_type": "DEPLOY_ERROR"}, "deploy") == RecoveryAction.ROLLBACK)
    check("TIMEOUT → RESTART",
          clf.classify({"status": "FAILED", "failure_type": "TIMEOUT"}, "build") == RecoveryAction.RESTART)
    check("SUCCESS → NONE",
          clf.classify({"status": "SUCCESS", "failure_type": None}, "deploy") == RecoveryAction.NONE)
    check("Unknown → ABORT",
          clf.classify({"status": "FAILED", "failure_type": "MYSTERY"}, "build") == RecoveryAction.ABORT)

    # ── Log Analyzer fallback ─────────────────────────────
    print("\n[LogAnalyzerClient — Fallback]")
    client   = LogAnalyzerClient(CFG)
    res_ok   = client._fallback_analyze("Build... SUCCESS\n10 passed, 0 failed")
    res_fail = client._fallback_analyze("npm ERR! 404\nBUILD FAILED")
    check("clean log → SUCCESS",        res_ok["status"]   == "SUCCESS")
    check("build fail → FAILED",        res_fail["status"] == "FAILED")
    check("build fail type",            res_fail["failure_type"] in ("BUILD_ERROR", "DEPENDENCY_ERROR"))
    check("fallback flag set",          res_fail.get("_fallback") is True)

    # ── PipelineRun model ─────────────────────────────────
    print("\n[Domain Models]")
    run = PipelineRun(pipeline_id="test-001", commit_sha="abc1234", branch="main")
    sr  = StageResult(name="build", job="app-build")
    att = StageAttempt(attempt=1, status=StageStatus.SUCCESS)
    sr.attempts.append(att)
    run.stages.append(sr)
    d = run.to_dict()
    check("to_dict has pipeline_id",    "pipeline_id" in d)
    check("stages serialised",          len(d["stages"]) == 1)
    check("last_attempt works",         sr.last_attempt is att)
    check("total_attempts = 1",         sr.total_attempts == 1)

    # ── Notification builder ──────────────────────────────
    print("\n[NotificationSystem — payload builder]")
    run.final_status = StageStatus.SUCCESS
    run.started_at   = datetime.now(timezone.utc).isoformat()
    run.finished_at  = datetime.now(timezone.utc).isoformat()
    notif  = NotificationSystem(CFG)
    subj, body, wh = notif._build_payloads(run, sr)
    check("subject contains pipeline_id",   run.pipeline_id in subj)
    check("body contains commit",           run.commit_sha in body)
    check("webhook status field",           wh["status"] == "SUCCESS")

    # ── ReportWriter ──────────────────────────────────────
    print("\n[ReportWriter]")
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_cfg    = dataclasses.replace(CFG, report_dir=tmpdir)  # type: ignore
        writer     = ReportWriter(tmp_cfg)
        saved_path = writer.save(run)
        loaded     = writer.load(run.pipeline_id)
        check("report file exists",     saved_path.exists())
        check("report loads correctly", loaded is not None and loaded["pipeline_id"] == run.pipeline_id)

    # ── Dry-run pipeline ──────────────────────────────────
    print("\n[PipelineController — dry-run]")
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_cfg = dataclasses.replace(  # type: ignore
            CFG, report_dir=tmpdir, log_analyzer_url="http://127.0.0.1:19999"
        )
        ctrl   = PipelineController(cfg=tmp_cfg, dry_run=True)
        result = ctrl.run(commit_sha="dryrun0", branch="test", stages=["build", "test"])
        check("dry-run completes",          result.final_status == StageStatus.SUCCESS)
        check("dry-run has 2 stages",       len(result.stages) == 2)
        check("dry-run build is SUCCESS",   result.stages[0].status == StageStatus.SUCCESS)
        check("report written for dry-run", (pathlib.Path(tmpdir) / f"{result.pipeline_id}_report.json").exists())

    # ── Summary ───────────────────────────────────────────
    print("\n" + "═" * 60)
    print(f"  Results: {passed} passed  |  {failed} failed")
    if errs:
        print(f"  Failed:  {', '.join(errs)}")
    print("═" * 60 + "\n")
    return failed == 0




def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog        = "pipeline_controller",
        description = f"CI/CD Pipeline Controller v{CFG.version}",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "examples:\n"
            "  python pipeline_controller.py --commit abc1234 --branch main\n"
            "  python pipeline_controller.py --commit abc1234 --stages build test\n"
            "  python pipeline_controller.py --commit abc1234 --dry-run\n"
            "  python pipeline_controller.py --serve --webhook-port 9000\n"
            "  python pipeline_controller.py --test\n"
        ),
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--serve",    action="store_true", help="Start webhook receiver server")
    mode.add_argument("--test",     action="store_true", help="Run built-in self-test suite")
    p.add_argument("--commit",       metavar="SHA",   default="HEAD",  help="Git commit SHA")
    p.add_argument("--branch",       metavar="NAME",  default="main",  help="Git branch name")
    p.add_argument("--stages",       nargs="+", choices=["build", "test", "deploy"],
                   help="Run specific stages only (default: all)")
    p.add_argument("--dry-run",      action="store_true", help="Skip Jenkins calls (testing)")
    p.add_argument("--webhook-host", default="0.0.0.0",  help="Webhook server bind host")
    p.add_argument("--webhook-port", type=int, default=9000, help="Webhook server port")
    return p


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    if args.test:
        ok = run_self_tests()
        sys.exit(0 if ok else 1)

    if args.serve:
        start_webhook_server(args.webhook_host, args.webhook_port)
        return

    controller = PipelineController(dry_run=args.dry_run)
    run = controller.run(
        commit_sha   = args.commit,
        branch       = args.branch,
        stages       = args.stages,
        triggered_by = "cli",
    )
    sys.exit(0 if run.final_status == StageStatus.SUCCESS else 1)


if __name__ == "__main__":
    main()
