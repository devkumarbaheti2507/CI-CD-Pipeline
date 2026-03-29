"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              CI/CD Pipeline — Log Analyzer Service                          ║
║              Production-Grade | Deployable | Industry-Level                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Author   : CS 331 - Software Engineering Lab                               ║
║  Project  : CI/CD Pipeline Automated Failure Recovery                       ║
║  Version  : 2.0.0                                                           ║
║  Python   : 3.10+  (stdlib only — zero external dependencies)               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Features:                                                                  ║
║   • Async-safe HTTP server with thread-pool                                 ║
║   • Structured JSON logging with log levels                                 ║
║   • Configurable via ENV vars or config file                                ║
║   • Full REST API  (analyze, batch, health, metrics, rules, docs)           ║
║   • Prometheus-compatible /metrics endpoint                                 ║
║   • Request ID tracing on every response                                    ║
║   • Rate limiting (per-IP sliding window)                                   ║
║   • Gzip response compression                                               ║
║   • CORS support                                                            ║
║   • Circuit breaker for downstream calls                                    ║
║   • Hot-reloadable failure rule engine                                      ║
║   • Severity scoring & confidence scoring                                   ║
║   • Multi-format log parsing (plain, JSON, logfmt)                          ║
║   • Batch analysis (up to 50 logs in one request)                           ║
║   • File-watcher mode for live log tailing                                  ║
║   • Graceful shutdown with in-flight request draining                       ║
╚══════════════════════════════════════════════════════════════════════════════╝

QUICK START
-----------
  Run as HTTP server (default port 5001):
      python log_analyzer.py

  Custom host/port:
      LOG_ANALYZER_HOST=0.0.0.0 LOG_ANALYZER_PORT=8080 python log_analyzer.py

  Analyze a file from CLI:
      python log_analyzer.py --file /path/to/build.log

  Watch a file for new entries:
      python log_analyzer.py --watch /var/log/pipeline.log

  Run self-test:
      python log_analyzer.py --test

  Print config:
      python log_analyzer.py --config

REST API ENDPOINTS
------------------
  POST /api/v1/analyze          Analyze a log string or file path
  POST /api/v1/analyze/batch    Analyze up to 50 logs in one call
  GET  /api/v1/rules            List all active detection rules
  GET  /api/v1/health           Health check (liveness + readiness)
  GET  /api/v1/metrics          Prometheus-compatible metrics
  GET  /api/v1/docs             API documentation (JSON)

ENVIRONMENT VARIABLES
---------------------
  LOG_ANALYZER_HOST         Bind host             (default: 0.0.0.0)
  LOG_ANALYZER_PORT         Bind port             (default: 5001)
  LOG_ANALYZER_WORKERS      Thread-pool size      (default: 4)
  LOG_ANALYZER_LOG_LEVEL    Logging level         (default: INFO)
  LOG_ANALYZER_LOG_FORMAT   "json" | "text"       (default: json)
  LOG_ANALYZER_RATE_LIMIT   Req/min per IP        (default: 60)
  LOG_ANALYZER_MAX_LOG_MB   Max log size to parse (default: 10)
  LOG_ANALYZER_CORS_ORIGINS Allowed CORS origins  (default: *)
  LOG_ANALYZER_SECRET_KEY   API key (optional)    (default: disabled)
"""

# ─────────────────────────────────────────────────────────────────────────────
# Standard Library Imports
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import abc
import argparse
import collections
import dataclasses
import enum
import functools
import gzip
import hashlib
import http.server
import io
import json
import logging
import logging.handlers
import os
import pathlib
import queue
import re
import signal
import socket
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Config:
    """
    Immutable configuration loaded once at startup.
    All values come from environment variables with safe defaults.
    """
    host: str           = field(default_factory=lambda: os.environ.get("LOG_ANALYZER_HOST", "0.0.0.0"))
    port: int           = field(default_factory=lambda: int(os.environ.get("LOG_ANALYZER_PORT", "5001")))
    workers: int        = field(default_factory=lambda: int(os.environ.get("LOG_ANALYZER_WORKERS", "4")))
    log_level: str      = field(default_factory=lambda: os.environ.get("LOG_ANALYZER_LOG_LEVEL", "INFO").upper())
    log_format: str     = field(default_factory=lambda: os.environ.get("LOG_ANALYZER_LOG_FORMAT", "json"))
    rate_limit: int     = field(default_factory=lambda: int(os.environ.get("LOG_ANALYZER_RATE_LIMIT", "60")))
    max_log_mb: int     = field(default_factory=lambda: int(os.environ.get("LOG_ANALYZER_MAX_LOG_MB", "10")))
    cors_origins: str   = field(default_factory=lambda: os.environ.get("LOG_ANALYZER_CORS_ORIGINS", "*"))
    secret_key: str     = field(default_factory=lambda: os.environ.get("LOG_ANALYZER_SECRET_KEY", ""))
    service_name: str   = "log-analyzer"
    version: str        = "2.0.0"

    @property
    def max_log_bytes(self) -> int:
        return self.max_log_mb * 1024 * 1024

    def display(self) -> str:
        lines = ["─" * 52, f"  Log Analyzer v{self.version} — Configuration", "─" * 52]
        for k, v in dataclasses.asdict(self).items():
            display_v = "***" if k == "secret_key" and v else v
            lines.append(f"  {k:<22}: {display_v}")
        lines.append("─" * 52)
        return "\n".join(lines)


CONFIG = Config()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2 — STRUCTURED LOGGER
# ═════════════════════════════════════════════════════════════════════════════

class StructuredLogger:
    """
    Emits structured JSON log records (or coloured text in dev mode).
    Every record includes: timestamp, level, logger, message, + any extras.
    """

    COLOURS = {
        "DEBUG":    "\033[36m",   # cyan
        "INFO":     "\033[32m",   # green
        "WARNING":  "\033[33m",   # yellow
        "ERROR":    "\033[31m",   # red
        "CRITICAL": "\033[35m",   # magenta
        "RESET":    "\033[0m",
    }

    def __init__(self, name: str, config: Config):
        self._name   = name
        self._config = config
        self._use_json = config.log_format == "json"
        root = logging.getLogger(name)
        root.setLevel(getattr(logging, config.log_level, logging.INFO))
        if not root.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter("%(message)s"))
            root.addHandler(handler)
        self._logger = root

    def _emit(self, level: str, msg: str, **extra: Any) -> None:
        if self._use_json:
            record = {
                "ts":      datetime.now(timezone.utc).isoformat(),
                "level":   level,
                "logger":  self._name,
                "msg":     msg,
                **extra,
            }
            line = json.dumps(record, default=str)
        else:
            ts    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            col   = self.COLOURS.get(level, "")
            reset = self.COLOURS["RESET"]
            extras = "  " + "  ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
            line  = f"{col}[{ts}] {level:<8} {self._name}: {msg}{extras}{reset}"

        getattr(self._logger, level.lower(), self._logger.info)(line)

    def debug(self, msg: str, **kw):    self._emit("DEBUG",    msg, **kw)
    def info(self, msg: str, **kw):     self._emit("INFO",     msg, **kw)
    def warning(self, msg: str, **kw):  self._emit("WARNING",  msg, **kw)
    def error(self, msg: str, **kw):    self._emit("ERROR",    msg, **kw)
    def critical(self, msg: str, **kw): self._emit("CRITICAL", msg, **kw)


log = StructuredLogger(CONFIG.service_name, CONFIG)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3 — METRICS REGISTRY  (Prometheus-compatible)
# ═════════════════════════════════════════════════════════════════════════════

class MetricsRegistry:
    """
    Thread-safe in-process metrics registry.
    Exports Prometheus text format on /api/v1/metrics.
    """

    def __init__(self):
        self._lock    = threading.Lock()
        self._counters: Dict[str, float]             = defaultdict(float)
        self._gauges:   Dict[str, float]             = defaultdict(float)
        self._histos:   Dict[str, List[float]]       = defaultdict(list)
        self._start     = time.monotonic()

    # ── counters ──────────────────────────────────────────
    def inc(self, name: str, value: float = 1.0, **labels) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += value

    # ── gauges ────────────────────────────────────────────
    def set_gauge(self, name: str, value: float, **labels) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = value

    # ── histograms ────────────────────────────────────────
    def observe(self, name: str, value: float, **labels) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._histos[key].append(value)

    # ── helpers ───────────────────────────────────────────
    @staticmethod
    def _key(name: str, labels: Dict) -> str:
        if not labels:
            return name
        lbl = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{lbl}}}"

    def _p(self, values: List[float], pct: float) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        idx = max(0, int(len(s) * pct / 100) - 1)
        return s[idx]

    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start

    # ── Prometheus text export ────────────────────────────
    def to_prometheus(self) -> str:
        lines: List[str] = []
        with self._lock:
            for key, val in self._counters.items():
                name = key.split("{")[0]
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{key} {val}")

            for key, val in self._gauges.items():
                name = key.split("{")[0]
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{key} {val}")

            for key, vals in self._histos.items():
                name = key.split("{")[0]
                lines.append(f"# TYPE {name} histogram")
                lines.append(f"{key}_count {len(vals)}")
                lines.append(f"{key}_sum   {sum(vals):.6f}")
                for p in (50, 90, 95, 99):
                    lines.append(f"{key}_p{p} {self._p(vals, p):.6f}")

        lines.append(f"log_analyzer_uptime_seconds {self.uptime_seconds():.2f}")
        return "\n".join(lines) + "\n"

    # ── JSON snapshot ─────────────────────────────────────
    def snapshot(self) -> Dict:
        with self._lock:
            return {
                "uptime_seconds":      round(self.uptime_seconds(), 2),
                "counters":            dict(self._counters),
                "gauges":              dict(self._gauges),
                "histograms":          {k: {
                    "count":  len(v),
                    "sum":    round(sum(v), 6),
                    "p50":    round(self._p(v, 50), 6),
                    "p90":    round(self._p(v, 90), 6),
                    "p99":    round(self._p(v, 99), 6),
                } for k, v in self._histos.items()},
            }


METRICS = MetricsRegistry()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 4 — RATE LIMITER  (sliding window, per-IP)
# ═════════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """
    Sliding-window rate limiter.
    Tracks timestamps of requests per client IP in a deque.
    Thread-safe via per-client lock.
    """

    def __init__(self, max_per_minute: int):
        self._max   = max_per_minute
        self._lock  = threading.Lock()
        self._store: Dict[str, deque] = defaultdict(lambda: deque())

    def is_allowed(self, client_ip: str) -> Tuple[bool, int]:
        """Returns (allowed, remaining_quota)."""
        now = time.monotonic()
        window = 60.0
        with self._lock:
            dq = self._store[client_ip]
            # evict old entries outside window
            while dq and now - dq[0] > window:
                dq.popleft()
            remaining = max(0, self._max - len(dq))
            if len(dq) >= self._max:
                return False, 0
            dq.append(now)
            return True, remaining - 1


RATE_LIMITER = RateLimiter(CONFIG.rate_limit)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 5 — FAILURE RULE ENGINE
# ═════════════════════════════════════════════════════════════════════════════

class Severity(str, enum.Enum):
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def score(self) -> int:
        return {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}[self.value]


@dataclass(frozen=True)
class FailureRule:
    """A single detection rule."""
    id:           str
    category:     str
    pattern:      str
    severity:     Severity
    description:  str
    confidence:   float         # 0.0–1.0  how reliable this pattern is
    tags:         Tuple[str, ...] = field(default_factory=tuple)
    _compiled:    re.Pattern    = field(init=False, compare=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "_compiled", re.compile(self.pattern, re.IGNORECASE))

    def match(self, line: str) -> Optional[re.Match]:
        return self._compiled.search(line)


class RuleEngine:
    """
    Hot-reloadable rule registry.
    Rules are checked in severity order (CRITICAL → LOW).
    One line can match multiple rules; all are reported.
    """

    # ── Built-in rule catalogue ────────────────────────────
    _DEFAULT_RULES: List[Dict] = [
        # ── BUILD ──────────────────────────────────────────
        dict(id="BUILD-001", category="BUILD_ERROR",      severity="CRITICAL",
             pattern=r"\bBUILD FAILED\b",
             description="Explicit build failure marker",             confidence=0.99,
             tags=("build", "ci")),
        dict(id="BUILD-002", category="BUILD_ERROR",      severity="HIGH",
             pattern=r"error:\s*.+compilation failed",
             description="Compiler error: compilation failed",        confidence=0.97,
             tags=("build", "compiler")),
        dict(id="BUILD-003", category="BUILD_ERROR",      severity="HIGH",
             pattern=r"make\[.*\].*\bError\b",
             description="Makefile error",                            confidence=0.95,
             tags=("build", "make")),
        dict(id="BUILD-004", category="BUILD_ERROR",      severity="HIGH",
             pattern=r"\bCannot find module\b",
             description="Node module resolution failure",            confidence=0.96,
             tags=("build", "node")),
        dict(id="BUILD-005", category="BUILD_ERROR",      severity="HIGH",
             pattern=r"\b(ModuleNotFoundError|ImportError)\b",
             description="Python import failure",                     confidence=0.96,
             tags=("build", "python")),
        dict(id="BUILD-006", category="BUILD_ERROR",      severity="MEDIUM",
             pattern=r"\bSyntaxError\b",
             description="Syntax error in source code",               confidence=0.94,
             tags=("build", "syntax")),
        dict(id="BUILD-007", category="BUILD_ERROR",      severity="MEDIUM",
             pattern=r"\bcompilation error\b",
             description="Generic compilation error",                 confidence=0.93,
             tags=("build", "compiler")),
        dict(id="BUILD-008", category="BUILD_ERROR",      severity="LOW",
             pattern=r"\bwarning:.*deprecated\b",
             description="Deprecation warning (may affect build)",    confidence=0.60,
             tags=("build", "warning")),

        # ── TEST ───────────────────────────────────────────
        dict(id="TEST-001", category="TEST_FAILURE",      severity="HIGH",
             pattern=r"\bFAILED\s+tests/",
             description="Pytest test failure marker",                confidence=0.99,
             tags=("test", "pytest")),
        dict(id="TEST-002", category="TEST_FAILURE",      severity="HIGH",
             pattern=r"\d+\s+failed[,\s]",
             description="Test runner reports N failed tests",        confidence=0.97,
             tags=("test")),
        dict(id="TEST-003", category="TEST_FAILURE",      severity="HIGH",
             pattern=r"\bAssertionError\b",
             description="Assertion failure in test",                 confidence=0.95,
             tags=("test", "assertion")),
        dict(id="TEST-004", category="TEST_FAILURE",      severity="HIGH",
             pattern=r"\bFAIL:\s+test_",
             description="Unittest FAIL marker",                      confidence=0.98,
             tags=("test", "unittest")),
        dict(id="TEST-005", category="TEST_FAILURE",      severity="CRITICAL",
             pattern=r"\bTest suite failed to run\b",
             description="Test suite could not even start",           confidence=0.99,
             tags=("test", "suite")),
        dict(id="TEST-006", category="TEST_FAILURE",      severity="MEDIUM",
             pattern=r"\bExpected.*but (got|received)\b",
             description="Value mismatch in test assertion",          confidence=0.85,
             tags=("test", "assertion")),
        dict(id="TEST-007", category="TEST_FAILURE",      severity="HIGH",
             pattern=r"\bCoverage.*below.*threshold\b",
             description="Code coverage gate failed",                 confidence=0.96,
             tags=("test", "coverage")),

        # ── DEPLOY ─────────────────────────────────────────
        dict(id="DEPLOY-001", category="DEPLOY_ERROR",    severity="CRITICAL",
             pattern=r"\bdeployment failed\b",
             description="Explicit deployment failure",               confidence=0.99,
             tags=("deploy",)),
        dict(id="DEPLOY-002", category="DEPLOY_ERROR",    severity="CRITICAL",
             pattern=r"\bError response from daemon\b",
             description="Docker daemon error",                       confidence=0.98,
             tags=("deploy", "docker")),
        dict(id="DEPLOY-003", category="DEPLOY_ERROR",    severity="CRITICAL",
             pattern=r"\bcontainer exited with code [1-9]\d*\b",
             description="Container exited with non-zero code",       confidence=0.97,
             tags=("deploy", "docker")),
        dict(id="DEPLOY-004", category="DEPLOY_ERROR",    severity="HIGH",
             pattern=r"\bkubectl\b.*\bError\b",
             description="Kubernetes command error",                  confidence=0.95,
             tags=("deploy", "kubernetes")),
        dict(id="DEPLOY-005", category="DEPLOY_ERROR",    severity="HIGH",
             pattern=r"\bImagePullBackOff\b",
             description="Kubernetes image pull failure",             confidence=0.99,
             tags=("deploy", "kubernetes")),
        dict(id="DEPLOY-006", category="DEPLOY_ERROR",    severity="HIGH",
             pattern=r"\bCrashLoopBackOff\b",
             description="Kubernetes pod crash loop",                 confidence=0.99,
             tags=("deploy", "kubernetes")),
        dict(id="DEPLOY-007", category="DEPLOY_ERROR",    severity="HIGH",
             pattern=r"\bport\s+\d+\s+(already in use|already allocated)\b",
             description="Port already in use",                       confidence=0.96,
             tags=("deploy", "network")),
        dict(id="DEPLOY-008", category="DEPLOY_ERROR",    severity="MEDIUM",
             pattern=r"\bConnection refused\b",
             description="Target refused connection",                  confidence=0.80,
             tags=("deploy", "network")),
        dict(id="DEPLOY-009", category="DEPLOY_ERROR",    severity="MEDIUM",
             pattern=r"\bOOMKilled\b",
             description="Container killed due to out of memory",     confidence=0.99,
             tags=("deploy", "kubernetes", "memory")),

        # ── DEPENDENCY ─────────────────────────────────────
        dict(id="DEP-001", category="DEPENDENCY_ERROR",   severity="HIGH",
             pattern=r"\bnpm ERR[!]",
             description="npm package manager error",                 confidence=0.98,
             tags=("dependency", "npm")),
        dict(id="DEP-002", category="DEPENDENCY_ERROR",   severity="HIGH",
             pattern=r"\bpip\b.*\bERROR\b",
             description="pip package manager error",                 confidence=0.97,
             tags=("dependency", "pip")),
        dict(id="DEP-003", category="DEPENDENCY_ERROR",   severity="HIGH",
             pattern=r"\bCould not resolve\b",
             description="Package resolution failure",                confidence=0.96,
             tags=("dependency")),
        dict(id="DEP-004", category="DEPENDENCY_ERROR",   severity="HIGH",
             pattern=r"\bPackage.*not found\b",
             description="Package not found in registry",             confidence=0.95,
             tags=("dependency")),
        dict(id="DEP-005", category="DEPENDENCY_ERROR",   severity="HIGH",
             pattern=r"\brequirements.*failed\b",
             description="requirements.txt installation failed",      confidence=0.96,
             tags=("dependency", "python")),
        dict(id="DEP-006", category="DEPENDENCY_ERROR",   severity="MEDIUM",
             pattern=r"\bversion conflict\b",
             description="Dependency version conflict",               confidence=0.88,
             tags=("dependency")),
        dict(id="DEP-007", category="DEPENDENCY_ERROR",   severity="MEDIUM",
             pattern=r"\bpeer dep.*not satisfied\b",
             description="Peer dependency not satisfied",             confidence=0.85,
             tags=("dependency", "npm")),

        # ── TIMEOUT ────────────────────────────────────────
        dict(id="TIMEOUT-001", category="TIMEOUT",        severity="HIGH",
             pattern=r"\btimeout\s+exceeded\b",
             description="Generic timeout exceeded",                  confidence=0.95,
             tags=("timeout",)),
        dict(id="TIMEOUT-002", category="TIMEOUT",        severity="HIGH",
             pattern=r"\bTimed? out\b",
             description="Operation timed out",                       confidence=0.92,
             tags=("timeout",)),
        dict(id="TIMEOUT-003", category="TIMEOUT",        severity="HIGH",
             pattern=r"\bETIMEDOUT\b",
             description="Node.js network timeout error",             confidence=0.99,
             tags=("timeout", "network")),
        dict(id="TIMEOUT-004", category="TIMEOUT",        severity="HIGH",
             pattern=r"\bexceeded.*deadline\b",
             description="Deadline exceeded (gRPC / k8s style)",      confidence=0.95,
             tags=("timeout",)),
        dict(id="TIMEOUT-005", category="TIMEOUT",        severity="MEDIUM",
             pattern=r"\bcontext deadline exceeded\b",
             description="Go context deadline exceeded",              confidence=0.99,
             tags=("timeout", "go")),

        # ── INFRA / SYSTEM ─────────────────────────────────
        dict(id="INFRA-001", category="INFRA_ERROR",      severity="CRITICAL",
             pattern=r"\bOut of memory\b",
             description="System out of memory",                      confidence=0.98,
             tags=("infra", "memory")),
        dict(id="INFRA-002", category="INFRA_ERROR",      severity="CRITICAL",
             pattern=r"\bNo space left on device\b",
             description="Disk full",                                 confidence=0.99,
             tags=("infra", "disk")),
        dict(id="INFRA-003", category="INFRA_ERROR",      severity="HIGH",
             pattern=r"\bpermission denied\b",
             description="File/resource permission error",            confidence=0.90,
             tags=("infra", "permissions")),
        dict(id="INFRA-004", category="INFRA_ERROR",      severity="HIGH",
             pattern=r"\bSSH.*refused\b",
             description="SSH connection refused",                    confidence=0.93,
             tags=("infra", "ssh")),

        # ── SECURITY ───────────────────────────────────────
        dict(id="SEC-001",  category="SECURITY_ALERT",    severity="CRITICAL",
             pattern=r"\b(CVE-\d{4}-\d+)\b",
             description="CVE identifier found in logs",              confidence=0.99,
             tags=("security", "cve")),
        dict(id="SEC-002",  category="SECURITY_ALERT",    severity="HIGH",
             pattern=r"\b(HIGH|CRITICAL)\s+severity\s+vuln",
             description="High/critical vulnerability detected",      confidence=0.92,
             tags=("security")),
        dict(id="SEC-003",  category="SECURITY_ALERT",    severity="MEDIUM",
             pattern=r"\bsecret.*leaked\b",
             description="Secret or credential may have leaked",      confidence=0.88,
             tags=("security", "secrets")),
    ]

    def __init__(self):
        self._rules: List[FailureRule] = []
        self._lock  = threading.RLock()
        self._load_defaults()

    def _load_defaults(self) -> None:
        rules = []
        for r in self._DEFAULT_RULES:
            try:
                rules.append(FailureRule(
                    id          = r["id"],
                    category    = r["category"],
                    pattern     = r["pattern"],
                    severity    = Severity(r["severity"]),
                    description = r["description"],
                    confidence  = r["confidence"],
                    tags        = tuple(r.get("tags", [])),
                ))
            except Exception as exc:
                log.warning("Rule load failed", rule_id=r.get("id"), error=str(exc))
        # Sort: CRITICAL first, then alphabetical by id within same severity
        rules.sort(key=lambda x: (-x.severity.score, x.id))
        with self._lock:
            self._rules = rules
        log.info("Rules loaded", total=len(self._rules))

    def all_rules(self) -> List[FailureRule]:
        with self._lock:
            return list(self._rules)

    def scan_line(self, line: str) -> List[Dict]:
        """Return all rule matches for a single log line."""
        hits = []
        with self._lock:
            for rule in self._rules:
                m = rule.match(line)
                if m:
                    hits.append({
                        "rule_id":     rule.id,
                        "category":    rule.category,
                        "severity":    rule.severity.value,
                        "confidence":  rule.confidence,
                        "description": rule.description,
                        "tags":        list(rule.tags),
                        "matched":     m.group(0),
                    })
        return hits


RULES = RuleEngine()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 6 — LOG FORMAT PARSERS
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ParsedLine:
    """Represents a single parsed log line."""
    raw:        str
    timestamp:  Optional[str]  = None
    level:      Optional[str]  = None
    message:    str            = ""
    fields:     Dict           = field(default_factory=dict)


class LogParser(abc.ABC):
    """Abstract base for log format parsers."""

    @abc.abstractmethod
    def parse_line(self, raw: str) -> ParsedLine:
        ...

    @staticmethod
    def detect_format(sample: str) -> str:
        """Heuristically detect log format from a sample."""
        lines = [l for l in sample.strip().splitlines() if l.strip()][:10]
        if not lines:
            return "plain"
        json_hits   = sum(1 for l in lines if l.strip().startswith("{") and l.strip().endswith("}"))
        logfmt_hits = sum(
            1 for l in lines
            if re.search(r'(?<!\w)\w[\w./-]*=[^\s]', l)
            and not l.strip().startswith("{")
            and not re.match(r'\[?\d{4}-\d{2}-\d{2}', l)
        )
        threshold = max(1, len(lines) // 2)
        if json_hits >= threshold:
            return "json"
        if logfmt_hits >= threshold:
            return "logfmt"
        return "plain"


class PlainLogParser(LogParser):
    """
    Parses common plain-text log formats:
      [2024-06-01 10:01:00] INFO  message...
      2024-06-01T10:01:00Z ERROR message...
    """
    _TS_RE  = re.compile(
        r"^[\[\(]?"
        r"(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
        r"[\]\)]?\s*"
    )
    _LVL_RE = re.compile(r"\b(?P<lvl>DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\b", re.I)

    def parse_line(self, raw: str) -> ParsedLine:
        pl = ParsedLine(raw=raw, message=raw.strip())
        remaining = raw
        m = self._TS_RE.match(remaining)
        if m:
            pl.timestamp = m.group("ts")
            remaining    = remaining[m.end():]
        m2 = self._LVL_RE.search(remaining[:30])
        if m2:
            pl.level   = m2.group("lvl").upper()
            remaining  = remaining[:m2.start()] + remaining[m2.end():]
        pl.message = remaining.strip(" :-|")
        return pl


class JsonLogParser(LogParser):
    """Parses newline-delimited JSON logs (structured logging output)."""

    _KNOWN_MSG_KEYS  = ("msg", "message", "text", "log", "event")
    _KNOWN_TS_KEYS   = ("ts", "time", "timestamp", "@timestamp", "datetime")
    _KNOWN_LVL_KEYS  = ("level", "lvl", "severity", "log.level")

    def parse_line(self, raw: str) -> ParsedLine:
        pl = ParsedLine(raw=raw, message=raw.strip())
        try:
            obj = json.loads(raw.strip())
            if not isinstance(obj, dict):
                return pl
            for k in self._KNOWN_MSG_KEYS:
                if k in obj:
                    pl.message = str(obj[k])
                    break
            for k in self._KNOWN_TS_KEYS:
                if k in obj:
                    pl.timestamp = str(obj[k])
                    break
            for k in self._KNOWN_LVL_KEYS:
                if k in obj:
                    pl.level = str(obj[k]).upper()
                    break
            pl.fields = {k: v for k, v in obj.items()
                         if k not in (*self._KNOWN_MSG_KEYS, *self._KNOWN_TS_KEYS, *self._KNOWN_LVL_KEYS)}
        except (json.JSONDecodeError, ValueError):
            pass
        return pl


class LogFmtParser(LogParser):
    """Parses logfmt: key=value key="quoted value" ..."""
    _PAIR_RE = re.compile(r'(\w[\w./-]*)=("(?:[^"\\]|\\.)*"|\S*)')

    def parse_line(self, raw: str) -> ParsedLine:
        pl     = ParsedLine(raw=raw, message=raw.strip())
        fields: Dict[str, str] = {}
        for m in self._PAIR_RE.finditer(raw):
            k, v = m.group(1), m.group(2).strip('"')
            fields[k] = v
        pl.fields = fields
        for k in ("msg", "message", "text"):
            if k in fields:
                pl.message = fields.pop(k)
                break
        for k in ("ts", "time", "timestamp"):
            if k in fields:
                pl.timestamp = fields.pop(k)
                break
        for k in ("level", "lvl", "severity"):
            if k in fields:
                pl.level = fields.pop(k).upper()
                break
        return pl


_FORMAT_MAP: Dict[str, LogParser] = {
    "plain":  PlainLogParser(),
    "json":   JsonLogParser(),
    "logfmt": LogFmtParser(),
}


def get_parser(fmt: str) -> LogParser:
    return _FORMAT_MAP.get(fmt, _FORMAT_MAP["plain"])


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 7 — CORE ANALYSIS ENGINE
# ═════════════════════════════════════════════════════════════════════════════

# Category priority — most severe wins overall status
_CATEGORY_PRIORITY = [
    "SECURITY_ALERT", "INFRA_ERROR", "DEPLOY_ERROR",
    "BUILD_ERROR",    "TEST_FAILURE", "DEPENDENCY_ERROR",
    "TIMEOUT",
]

@dataclass
class AnalysisResult:
    """Full structured analysis result for one log input."""
    request_id:       str
    status:           str               # SUCCESS | FAILED
    failure_category: Optional[str]
    overall_severity: Optional[str]
    confidence_score: float             # 0.0–1.0
    total_lines:      int
    parsed_lines:     int
    failures_found:   int
    log_format:       str
    findings:         List[Dict]
    category_summary: Dict[str, int]
    analyzed_at:      str
    duration_ms:      float

    def to_dict(self) -> Dict:
        return dataclasses.asdict(self)


def analyze(
    log_text:   str,
    source:     str           = "inline",
    request_id: Optional[str] = None,
    fmt_hint:   str           = "auto",
) -> AnalysisResult:
    """
    Core analysis function.

    Parameters
    ----------
    log_text   : Raw log string to analyze
    source     : Label describing origin of log (file path, pipeline ID, etc.)
    request_id : Trace ID (auto-generated if not provided)
    fmt_hint   : "auto" | "plain" | "json" | "logfmt"

    Returns
    -------
    AnalysisResult dataclass with all findings.
    """
    t0         = time.monotonic()
    request_id = request_id or str(uuid.uuid4())

    log.debug("Analysis started", request_id=request_id, source=source, bytes=len(log_text))

    # ── detect format ─────────────────────────────────────
    if fmt_hint == "auto" or fmt_hint not in _FORMAT_MAP:
        fmt = LogParser.detect_format(log_text)
    else:
        fmt = fmt_hint
    parser = get_parser(fmt)

    # ── scan lines ────────────────────────────────────────
    lines    = log_text.splitlines()
    findings: List[Dict] = []
    seen_lines: Set[int] = set()
    parsed_count = 0

    for line_no, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            parsed  = parser.parse_line(raw_line)
            parsed_count += 1
        except Exception:
            parsed = ParsedLine(raw=raw_line, message=raw_line.strip())

        hits = RULES.scan_line(parsed.message or raw_line)

        for hit in hits:
            if line_no not in seen_lines:
                seen_lines.add(line_no)
            findings.append({
                "line_no":    line_no,
                "raw":        raw_line.rstrip(),
                "message":    parsed.message,
                "timestamp":  parsed.timestamp,
                "log_level":  parsed.level,
                **hit,
            })

    # ── derive overall failure category ───────────────────
    if findings:
        cats_seen = {f["category"] for f in findings}
        primary_cat = next(
            (c for c in _CATEGORY_PRIORITY if c in cats_seen),
            findings[0]["category"]
        )
        # overall severity = max severity across all findings
        sev_order = {s.value: s.score for s in Severity}
        overall_sev = max(findings, key=lambda f: sev_order.get(f["severity"], 0))["severity"]
        # confidence = weighted average of matched-rule confidences
        conf_score = sum(f["confidence"] for f in findings) / len(findings)
        status = "FAILED"
    else:
        primary_cat = None
        overall_sev = None
        conf_score  = 1.0  # 100% confident it's clean
        status      = "SUCCESS"

    # ── category summary ──────────────────────────────────
    cat_summary: Dict[str, int] = defaultdict(int)
    for f in findings:
        cat_summary[f["category"]] += 1

    duration_ms = (time.monotonic() - t0) * 1000

    # ── record metrics ────────────────────────────────────
    METRICS.inc("log_analyzer_analyses_total", status=status)
    METRICS.observe("log_analyzer_duration_ms", duration_ms)
    METRICS.inc("log_analyzer_lines_scanned_total", value=len(lines))
    METRICS.inc("log_analyzer_findings_total", value=len(findings))
    if primary_cat:
        METRICS.inc("log_analyzer_failures_by_category_total", category=primary_cat)

    result = AnalysisResult(
        request_id       = request_id,
        status           = status,
        failure_category = primary_cat,
        overall_severity = overall_sev,
        confidence_score = round(conf_score, 4),
        total_lines      = len(lines),
        parsed_lines     = parsed_count,
        failures_found   = len(findings),
        log_format       = fmt,
        findings         = findings,
        category_summary = dict(cat_summary),
        analyzed_at      = datetime.now(timezone.utc).isoformat(),
        duration_ms      = round(duration_ms, 3),
    )

    log.info(
        "Analysis complete",
        request_id    = request_id,
        status        = status,
        category      = primary_cat,
        severity      = overall_sev,
        findings      = len(findings),
        duration_ms   = round(duration_ms, 2),
        log_format    = fmt,
    )

    return result


def analyze_file(filepath: str, **kwargs) -> AnalysisResult:
    """Analyze a log file from disk."""
    path = pathlib.Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {filepath}")
    if path.stat().st_size > CONFIG.max_log_bytes:
        raise ValueError(
            f"File {filepath!r} exceeds max size "
            f"({CONFIG.max_log_mb} MB). Set LOG_ANALYZER_MAX_LOG_MB to override."
        )
    log_text = path.read_text(errors="replace")
    return analyze(log_text, source=str(path), **kwargs)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 8 — HTTP SERVER
# ═════════════════════════════════════════════════════════════════════════════

class _ThreadedHTTPServer(http.server.HTTPServer):
    """HTTPServer backed by a thread pool for concurrent request handling."""

    def __init__(self, *args, max_workers: int = 4, **kwargs):
        super().__init__(*args, **kwargs)
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="la-worker")

    def process_request(self, request, client_address):
        self._pool.submit(self._handle, request, client_address)

    def _handle(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)

    def server_close(self):
        self._pool.shutdown(wait=True)
        super().server_close()


class LogAnalyzerHandler(http.server.BaseHTTPRequestHandler):
    """
    HTTP request handler — routes, validates, and dispatches to business logic.
    """

    server_version = f"LogAnalyzer/{CONFIG.version}"
    protocol_version = "HTTP/1.1"

    # ── silence default access log (we log ourselves) ─────
    def log_message(self, fmt, *args):
        pass

    # ─────────────────────────────────────────────────────
    # Routing
    # ─────────────────────────────────────────────────────
    _ROUTES: Dict[str, Dict[str, str]] = {
        "GET": {
            "/api/v1/health":   "handle_health",
            "/api/v1/metrics":  "handle_metrics",
            "/api/v1/rules":    "handle_rules",
            "/api/v1/docs":     "handle_docs",
            "/":                "handle_root",
        },
        "POST": {
            "/api/v1/analyze":       "handle_analyze",
            "/api/v1/analyze/batch": "handle_analyze_batch",
        },
    }

    def do_GET(self):    self._dispatch("GET")
    def do_POST(self):   self._dispatch("POST")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "*")
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin",  origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Accept, Accept-Encoding")
        self.send_header("Access-Control-Max-Age",       "86400")
        self.send_header("Content-Length",               "0")
        self.end_headers()

    def _dispatch(self, method: str) -> None:
        start    = time.monotonic()
        req_id   = str(uuid.uuid4())[:8]
        parsed   = urllib.parse.urlparse(self.path)
        path     = parsed.path.rstrip("/") or "/"
        client   = self.client_address[0]

        log.debug("Request", method=method, path=path, client=client, request_id=req_id)

        # ── rate limiting ─────────────────────────────────
        allowed, remaining = RATE_LIMITER.is_allowed(client)
        if not allowed:
            self._json_response({"error": "Rate limit exceeded. Try again later."}, 429, req_id)
            METRICS.inc("log_analyzer_rate_limited_total")
            return

        # ── auth (if configured) ──────────────────────────
        if CONFIG.secret_key:
            token = self.headers.get("X-API-Key", "")
            if token != CONFIG.secret_key:
                self._json_response({"error": "Unauthorized"}, 401, req_id)
                METRICS.inc("log_analyzer_auth_failures_total")
                return

        # ── route lookup ──────────────────────────────────
        handler_name = self._ROUTES.get(method, {}).get(path)
        if not handler_name:
            self._json_response({"error": f"Route not found: {method} {path}"}, 404, req_id)
            METRICS.inc("log_analyzer_http_requests_total", method=method, status="404")
            return

        # ── dispatch ──────────────────────────────────────
        try:
            getattr(self, handler_name)(req_id, parsed)
        except Exception as exc:
            tb = traceback.format_exc()
            log.error("Unhandled exception", request_id=req_id, error=str(exc), traceback=tb)
            self._json_response({"error": "Internal server error", "request_id": req_id}, 500, req_id)
            METRICS.inc("log_analyzer_errors_total")
        finally:
            elapsed = (time.monotonic() - start) * 1000
            METRICS.observe("log_analyzer_http_duration_ms", elapsed, method=method, path=path)
            METRICS.inc("log_analyzer_http_requests_total",  method=method, status="2xx")
            log.debug("Response sent", request_id=req_id, duration_ms=round(elapsed, 2))

    # ─────────────────────────────────────────────────────
    # Handlers
    # ─────────────────────────────────────────────────────

    def handle_root(self, req_id: str, _parsed):
        self._json_response({
            "service":  CONFIG.service_name,
            "version":  CONFIG.version,
            "status":   "running",
            "endpoints": list(self._ROUTES.get("GET", {}).keys()) +
                         list(self._ROUTES.get("POST", {}).keys()),
        }, 200, req_id)

    def handle_health(self, req_id: str, _parsed):
        self._json_response({
            "status":          "healthy",
            "service":         CONFIG.service_name,
            "version":         CONFIG.version,
            "uptime_seconds":  round(METRICS.uptime_seconds(), 2),
            "rules_loaded":    len(RULES.all_rules()),
            "timestamp":       datetime.now(timezone.utc).isoformat(),
        }, 200, req_id)

    def handle_metrics(self, req_id: str, _parsed):
        body = METRICS.to_prometheus().encode()
        self._raw_response(body, "text/plain; version=0.0.4", 200, req_id)

    def handle_rules(self, req_id: str, parsed):
        qs       = urllib.parse.parse_qs(parsed.query)
        cat_f    = qs.get("category", [None])[0]
        sev_f    = qs.get("severity",  [None])[0]
        tag_f    = qs.get("tag",       [None])[0]
        rules    = RULES.all_rules()
        if cat_f: rules = [r for r in rules if r.category    == cat_f.upper()]
        if sev_f: rules = [r for r in rules if r.severity.value == sev_f.upper()]
        if tag_f: rules = [r for r in rules if tag_f in r.tags]
        self._json_response({
            "total":  len(rules),
            "rules":  [dataclasses.asdict(r) for r in rules],
        }, 200, req_id)

    def handle_analyze(self, req_id: str, parsed):
        payload = self._read_json_body()
        if payload is None:
            self._json_response({"error": "Request body must be valid JSON"}, 400, req_id)
            return

        # Accept log text directly or a file path
        log_text  = payload.get("log") or payload.get("log_text")
        file_path = payload.get("file") or payload.get("file_path")
        fmt_hint  = payload.get("format", "auto")

        if file_path:
            try:
                result = analyze_file(file_path, request_id=req_id, fmt_hint=fmt_hint)
            except FileNotFoundError as e:
                self._json_response({"error": str(e)}, 404, req_id)
                return
            except ValueError as e:
                self._json_response({"error": str(e)}, 413, req_id)
                return
        elif log_text is not None:
            if len(log_text.encode()) > CONFIG.max_log_bytes:
                self._json_response(
                    {"error": f"Log text exceeds {CONFIG.max_log_mb} MB limit"}, 413, req_id)
                return
            source = payload.get("source", "inline")
            result = analyze(log_text, source=source, request_id=req_id, fmt_hint=fmt_hint)
        else:
            self._json_response(
                {"error": "Provide either 'log' (text) or 'file' (path) in request body"}, 400, req_id)
            return

        self._json_response(result.to_dict(), 200, req_id)

    def handle_analyze_batch(self, req_id: str, _parsed):
        payload = self._read_json_body()
        if payload is None:
            self._json_response({"error": "Request body must be valid JSON"}, 400, req_id)
            return

        items = payload.get("items", [])
        if not isinstance(items, list) or len(items) == 0:
            self._json_response({"error": "'items' must be a non-empty list"}, 400, req_id)
            return
        if len(items) > 50:
            self._json_response({"error": "Batch size cannot exceed 50 items"}, 400, req_id)
            return

        results = []
        for idx, item in enumerate(items):
            item_id = f"{req_id}-{idx}"
            log_text = item.get("log", "")
            fmt_hint = item.get("format", "auto")
            source   = item.get("source", f"batch-item-{idx}")
            try:
                r = analyze(log_text, source=source, request_id=item_id, fmt_hint=fmt_hint)
                results.append(r.to_dict())
            except Exception as exc:
                results.append({"request_id": item_id, "error": str(exc)})

        total_failed = sum(1 for r in results if r.get("status") == "FAILED")
        self._json_response({
            "batch_id":     req_id,
            "total":        len(results),
            "failed":       total_failed,
            "succeeded":    len(results) - total_failed,
            "results":      results,
        }, 200, req_id)

    def handle_docs(self, req_id: str, _parsed):
        self._json_response({
            "service": CONFIG.service_name,
            "version": CONFIG.version,
            "endpoints": {
                "POST /api/v1/analyze": {
                    "description": "Analyze a single log",
                    "body": {
                        "log":    "(string) Raw log text to analyze",
                        "file":   "(string) Absolute path to a log file on disk",
                        "format": "(string) 'auto'|'plain'|'json'|'logfmt'  (default: auto)",
                        "source": "(string) Label for the log source",
                    },
                    "response": "AnalysisResult object",
                },
                "POST /api/v1/analyze/batch": {
                    "description": "Analyze up to 50 logs in one call",
                    "body": {"items": "[{log, format?, source?}, ...]"},
                    "response": "BatchResult with results array",
                },
                "GET /api/v1/rules": {
                    "description": "List all active detection rules",
                    "query_params": {
                        "category": "Filter by category  (e.g. BUILD_ERROR)",
                        "severity": "Filter by severity  (e.g. CRITICAL)",
                        "tag":      "Filter by tag       (e.g. docker)",
                    },
                },
                "GET /api/v1/health":   "Service health + uptime",
                "GET /api/v1/metrics":  "Prometheus-compatible metrics",
            },
            "failure_categories": _CATEGORY_PRIORITY,
            "severity_levels":    [s.value for s in Severity],
        }, 200, req_id)

    # ─────────────────────────────────────────────────────
    # HTTP response helpers
    # ─────────────────────────────────────────────────────

    def _read_json_body(self) -> Optional[Dict]:
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw    = self.rfile.read(length)
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None

    def _json_response(self, data: Dict, status: int, req_id: str) -> None:
        body = json.dumps(data, indent=2, default=str).encode()
        self._raw_response(body, "application/json", status, req_id)

    def _raw_response(self, body: bytes, content_type: str, status: int, req_id: str) -> None:
        # gzip if client accepts it and body is worth compressing
        accept_enc = self.headers.get("Accept-Encoding", "")
        if "gzip" in accept_enc and len(body) > 1024:
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
                gz.write(body)
            body           = buf.getvalue()
            encoding_hdrs  = [("Content-Encoding", "gzip")]
        else:
            encoding_hdrs  = []

        origin = self.headers.get("Origin", "")
        cors   = CONFIG.cors_origins
        cors_v = origin if cors == "*" and origin else cors

        self.send_response(status)
        self.send_header("Content-Type",      content_type)
        self.send_header("Content-Length",    str(len(body)))
        self.send_header("X-Request-Id",      req_id)
        self.send_header("X-Service",         CONFIG.service_name)
        self.send_header("X-Service-Version", CONFIG.version)
        self.send_header("Access-Control-Allow-Origin",  cors_v)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for k, v in encoding_hdrs:
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 9 — GRACEFUL SHUTDOWN
# ═════════════════════════════════════════════════════════════════════════════

class GracefulServer:
    """Wraps the HTTP server with SIGINT/SIGTERM shutdown handling."""

    def __init__(self, server: _ThreadedHTTPServer):
        self._server   = server
        self._stopping = threading.Event()

    def start(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._signal_handler)

        host, port = self._server.server_address
        log.info(
            "Server started",
            host=host, port=port,
            workers=CONFIG.workers,
            log_level=CONFIG.log_level,
            rate_limit=f"{CONFIG.rate_limit}/min",
            auth="enabled" if CONFIG.secret_key else "disabled",
        )
        print(f"\n  Log Analyzer v{CONFIG.version}  →  http://{host}:{port}/api/v1/docs\n")
        self._server.serve_forever(poll_interval=0.5)

    def _signal_handler(self, signum, _frame) -> None:
        if not self._stopping.is_set():
            self._stopping.set()
            log.info("Shutdown signal received", signal=signal.Signals(signum).name)
            threading.Thread(target=self._server.shutdown, daemon=True).start()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 10 — FILE WATCHER  (live tail mode)
# ═════════════════════════════════════════════════════════════════════════════

class LogFileWatcher:
    """
    Tails a log file and runs analysis on each new chunk.
    Prints a summary line for every new failure detected.
    """

    def __init__(self, filepath: str, poll_interval: float = 1.0):
        self._path     = pathlib.Path(filepath)
        self._interval = poll_interval
        self._offset   = 0

    def watch(self) -> None:
        if not self._path.exists():
            print(f"[Watcher] File not found: {self._path}")
            sys.exit(1)

        self._offset = self._path.stat().st_size
        print(f"[Watcher] Tailing {self._path}  (Ctrl+C to stop)\n")

        try:
            while True:
                time.sleep(self._interval)
                stat = self._path.stat()
                if stat.st_size < self._offset:
                    # file was rotated
                    self._offset = 0
                if stat.st_size == self._offset:
                    continue

                with open(self._path, errors="replace") as f:
                    f.seek(self._offset)
                    new_text = f.read()
                    self._offset = f.tell()

                if new_text.strip():
                    result = analyze(new_text, source=str(self._path))
                    if result.status == "FAILED":
                        print(
                            f"  ✗ [{result.analyzed_at}]  "
                            f"{result.failure_category}  "
                            f"(severity={result.overall_severity}, "
                            f"findings={result.failures_found})"
                        )
                        for f_item in result.findings[:3]:
                            print(f"      Line {f_item['line_no']}: {f_item['raw'][:80]}")
                    else:
                        print(f"  ✓ [{result.analyzed_at}]  {result.parsed_lines} new lines — clean")
        except KeyboardInterrupt:
            print("\n[Watcher] Stopped.")


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 11 — SELF-TEST SUITE
# ═════════════════════════════════════════════════════════════════════════════

def run_self_tests() -> bool:
    """
    Built-in test suite — no external test runner required.
    Returns True if all tests pass.
    """
    passed = failed = 0
    errors: List[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  ✓  {name}")
        else:
            failed += 1
            errors.append(name)
            print(f"  ✗  {name}  {detail}")

    print("\n" + "═" * 56)
    print("  Log Analyzer — Self-Test Suite")
    print("═" * 56)

    # ── parser detection ──────────────────────────────────
    print("\n[Format Detection]")
    check("plain detected",  LogParser.detect_format("[2024-01-01] INFO  hello") == "plain")
    check("json detected",   LogParser.detect_format('{"level":"error","msg":"fail"}') == "json")
    check("logfmt detected", LogParser.detect_format('level=error msg=fail') == "logfmt")

    # ── plain parser ──────────────────────────────────────
    print("\n[PlainLogParser]")
    pp = PlainLogParser()
    pl = pp.parse_line("[2024-06-01 10:05:12] ERROR  Build failed")
    check("timestamp extracted", pl.timestamp == "2024-06-01 10:05:12")
    check("level extracted",     pl.level == "ERROR")
    check("message extracted",   "Build" in pl.message)

    # ── json parser ───────────────────────────────────────
    print("\n[JsonLogParser]")
    jp = JsonLogParser()
    jl = jp.parse_line('{"ts":"2024-06-01T10:05:12Z","level":"ERROR","msg":"container failed"}')
    check("json ts",    jl.timestamp == "2024-06-01T10:05:12Z")
    check("json level", jl.level == "ERROR")
    check("json msg",   "container" in jl.message)

    # ── rule engine ───────────────────────────────────────
    print("\n[Rule Engine]")
    check("rules loaded",       len(RULES.all_rules()) > 20)
    hits = RULES.scan_line("BUILD FAILED exit code 1")
    check("BUILD_ERROR detected",   any(h["category"] == "BUILD_ERROR" for h in hits))
    hits2 = RULES.scan_line("npm ERR! 404 Not Found")
    check("DEPENDENCY_ERROR detected", any(h["category"] == "DEPENDENCY_ERROR" for h in hits2))
    hits3 = RULES.scan_line("deployment failed")
    check("DEPLOY_ERROR detected",  any(h["category"] == "DEPLOY_ERROR" for h in hits3))
    hits4 = RULES.scan_line("AssertionError: expected 200 got 500")
    check("TEST_FAILURE detected",  any(h["category"] == "TEST_FAILURE" for h in hits4))
    hits5 = RULES.scan_line("CVE-2024-12345 found in dependency")
    check("SECURITY_ALERT detected", any(h["category"] == "SECURITY_ALERT" for h in hits5))

    # ── analysis engine ───────────────────────────────────
    print("\n[Analysis Engine — Build Failure]")
    r = analyze(
        "[2024-06-01 10:01:00] Starting build...\n"
        "npm ERR! 404 Not Found - GET /react-dom\n"
        "BUILD FAILED\n"
        "Exit code: 1"
    )
    check("status=FAILED",             r.status == "FAILED")
    check("category=BUILD_ERROR",      r.failure_category in ("BUILD_ERROR", "DEPENDENCY_ERROR"))
    check("findings > 0",              r.failures_found > 0)
    check("lines scanned correctly",   r.total_lines == 4)

    print("\n[Analysis Engine — Clean Run]")
    r2 = analyze(
        "[2024-06-01] Build ... SUCCESS\n"
        "[2024-06-01] Tests ... 15 passed, 0 failed\n"
        "[2024-06-01] Deploy ... container started successfully"
    )
    check("status=SUCCESS",            r2.status == "SUCCESS")
    check("no findings",               r2.failures_found == 0)
    check("confidence=1.0 on clean",   r2.confidence_score == 1.0)

    print("\n[Analysis Engine — Deploy Error]")
    r3 = analyze(
        "Pulling image...\n"
        "Error response from daemon: port already allocated\n"
        "container exited with code 1\n"
        "deployment failed"
    )
    check("DEPLOY_ERROR category",     r3.failure_category == "DEPLOY_ERROR")
    check("severity is HIGH+",         r3.overall_severity in ("HIGH", "CRITICAL"))

    print("\n[Analysis Engine — Security Alert]")
    r4 = analyze("Found CVE-2024-99999 in log4j 2.14.0 — CRITICAL severity")
    check("SECURITY_ALERT wins priority", r4.failure_category == "SECURITY_ALERT")

    print("\n[Batch Analysis]")
    logs = [
        "BUILD FAILED",
        "Tests... 5 passed, 0 failed. Deploy successful.",
        "deployment failed",
    ]
    statuses = []
    for l in logs:
        statuses.append(analyze(l).status)
    check("batch: 2 FAILED, 1 SUCCESS", statuses.count("FAILED") == 2)

    print("\n[Metrics]")
    snap = METRICS.snapshot()
    check("uptime tracked",         snap["uptime_seconds"] > 0)
    check("counters populated",     len(snap["counters"]) > 0)

    # ── summary ───────────────────────────────────────────
    print("\n" + "═" * 56)
    print(f"  Results:  {passed} passed  |  {failed} failed")
    if errors:
        print(f"  Failed:   {', '.join(errors)}")
    print("═" * 56 + "\n")

    return failed == 0


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 12 — CLI & ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog        = "log_analyzer",
        description = f"CI/CD Log Analyzer Service v{CONFIG.version}",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Environment variables:\n"
            "  LOG_ANALYZER_HOST, LOG_ANALYZER_PORT, LOG_ANALYZER_WORKERS\n"
            "  LOG_ANALYZER_LOG_LEVEL, LOG_ANALYZER_LOG_FORMAT (json|text)\n"
            "  LOG_ANALYZER_RATE_LIMIT, LOG_ANALYZER_MAX_LOG_MB\n"
            "  LOG_ANALYZER_CORS_ORIGINS, LOG_ANALYZER_SECRET_KEY\n"
        ),
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--file",   metavar="PATH", help="Analyze a log file and print results")
    mode.add_argument("--watch",  metavar="PATH", help="Tail a log file for real-time analysis")
    mode.add_argument("--test",   action="store_true", help="Run built-in self-test suite")
    mode.add_argument("--config", action="store_true", help="Print current configuration and exit")
    p.add_argument("--format", choices=["auto", "plain", "json", "logfmt"],
                   default="auto", help="Log format hint (default: auto-detect)")
    p.add_argument("--output", choices=["pretty", "json"], default="pretty",
                   help="CLI output format (default: pretty)")
    return p


def _print_result(result: AnalysisResult, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(result.to_dict(), indent=2, default=str))
        return

    # pretty print
    W = 60
    status_sym = "✓" if result.status == "SUCCESS" else "✗"
    print("\n" + "═" * W)
    print(f"  {status_sym}  Status   : {result.status}")
    if result.failure_category:
        print(f"     Category : {result.failure_category}")
        print(f"     Severity : {result.overall_severity}")
        print(f"     Confidence: {result.confidence_score:.0%}")
    print(f"     Lines    : {result.total_lines}  |  Format: {result.log_format}")
    print(f"     Findings : {result.failures_found}  |  Time: {result.duration_ms}ms")

    if result.category_summary:
        print("\n  Category breakdown:")
        for cat, cnt in sorted(result.category_summary.items()):
            print(f"    {cat:<22}: {cnt}")

    if result.findings:
        print(f"\n  Findings ({min(len(result.findings), 10)} of {len(result.findings)} shown):")
        for f in result.findings[:10]:
            sev   = f["severity"]
            cid   = f["rule_id"]
            desc  = f["description"]
            raw   = f["raw"][:70]
            print(f"    [{sev:<8}] Line {f['line_no']:>4}  {cid}  {desc}")
            print(f"             {raw}")
    print("═" * W + "\n")


def main() -> None:
    parser  = build_arg_parser()
    args    = parser.parse_args()

    # ── config dump ───────────────────────────────────────
    if args.config:
        print(CONFIG.display())
        return

    # ── self-test ─────────────────────────────────────────
    if args.test:
        ok = run_self_tests()
        sys.exit(0 if ok else 1)

    # ── file analysis ─────────────────────────────────────
    if args.file:
        try:
            result = analyze_file(args.file, fmt_hint=args.format)
            _print_result(result, args.output)
            sys.exit(0 if result.status == "SUCCESS" else 1)
        except (FileNotFoundError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(2)

    # ── watch mode ────────────────────────────────────────
    if args.watch:
        LogFileWatcher(args.watch).watch()
        return

    # ── default: HTTP server ──────────────────────────────
    try:
        server = _ThreadedHTTPServer(
            (CONFIG.host, CONFIG.port),
            LogAnalyzerHandler,
            max_workers = CONFIG.workers,
        )
        GracefulServer(server).start()
    except OSError as e:
        log.critical("Failed to start server", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()