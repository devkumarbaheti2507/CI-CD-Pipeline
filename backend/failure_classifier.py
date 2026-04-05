import os
import re
import logging
import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("failure-classifier")

MAX_AUTO_RETRIES = int(os.getenv("MAX_AUTO_RETRIES", "2"))

PROD_BRANCHES = {"main", "master", "production"}


class FailureType(str, Enum):
    BUILD_ERROR      = "BUILD_ERROR"
    TEST_FAILURE     = "TEST_FAILURE"
    DEPLOY_ERROR     = "DEPLOY_ERROR"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    TIMEOUT          = "TIMEOUT"
    CONFIG_ERROR     = "CONFIG_ERROR"
    UNKNOWN          = "UNKNOWN"
    NONE             = "NONE"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH     = "HIGH"
    MEDIUM   = "MEDIUM"
    LOW      = "LOW"
    NONE     = "NONE"


class RecoveryAction(str, Enum):
    RETRY      = "RETRY"
    ROLLBACK   = "ROLLBACK"
    RESTART    = "RESTART"
    ALERT_ONLY = "ALERT_ONLY"
    MANUAL     = "MANUAL"
    NONE       = "NONE"


class AnalysisInput(BaseModel):
    status:         str
    failure_type:   Optional[str] = None
    failures_found: int           = 0
    details:        list          = []


class ClassifyRequest(BaseModel):
    pipeline_id:   str
    stage:         str
    analysis:      AnalysisInput
    attempt:       int           = 1
    branch:        Optional[str] = None
    run_number:    Optional[int] = None


class ClassifyResponse(BaseModel):
    pipeline_id:   str
    failure_type:  FailureType
    severity:      Severity
    recovery:      RecoveryAction
    is_production: bool
    escalated:     bool
    reason:        str
    classified_at: str


RAW_TO_FAILURE_TYPE = {
    "BUILD_ERROR":      FailureType.BUILD_ERROR,
    "TEST_FAILURE":     FailureType.TEST_FAILURE,
    "DEPLOY_ERROR":     FailureType.DEPLOY_ERROR,
    "DEPENDENCY_ERROR": FailureType.DEPENDENCY_ERROR,
    "TIMEOUT":          FailureType.TIMEOUT,
    "CONFIG_ERROR":     FailureType.CONFIG_ERROR,
    "SUCCESS":          FailureType.NONE,
}

CONTENT_PATTERNS = [
    (re.compile(r"missing.*env|undefined.*var|config.*not.*found|ENOENT", re.I), FailureType.CONFIG_ERROR),
    (re.compile(r"401|403|Unauthorized|forbidden",                         re.I), FailureType.DEPENDENCY_ERROR),
    (re.compile(r"timeout|timed out",                                      re.I), FailureType.TIMEOUT),
]


def normalise_failure_type(raw: Optional[str], findings: list) -> FailureType:
    base = RAW_TO_FAILURE_TYPE.get((raw or "").upper(), FailureType.UNKNOWN)

    if base in (FailureType.UNKNOWN, FailureType.BUILD_ERROR):
        content = " ".join(f.get("content", "") for f in findings)
        for pattern, refined in CONTENT_PATTERNS:
            if pattern.search(content):
                return refined

    return base


def is_production(branch: Optional[str]) -> bool:
    if not branch:
        return False
    return branch.lower() in PROD_BRANCHES or branch.lower().startswith("release/")


def classify(
    failure_type: FailureType,
    stage:        str,
    attempt:      int,
    prod:         bool,
) -> tuple:
    escalated = attempt > MAX_AUTO_RETRIES

    if failure_type == FailureType.NONE:
        return Severity.NONE, RecoveryAction.NONE, False, "Pipeline succeeded"

    if failure_type == FailureType.DEPLOY_ERROR:
        if prod:
            return Severity.CRITICAL, RecoveryAction.ROLLBACK, escalated, \
                   "Deploy failed on production — rollback triggered"
        if escalated:
            return Severity.HIGH, RecoveryAction.MANUAL, True, \
                   f"Deploy failed after {attempt} attempts — manual review required"
        return Severity.HIGH, RecoveryAction.RETRY, False, \
               f"Deploy failed on non-production (attempt {attempt}) — retrying"

    if failure_type == FailureType.BUILD_ERROR:
        if escalated:
            return Severity.HIGH, RecoveryAction.ALERT_ONLY, True, \
                   f"Build failed after {attempt} attempts — alerting team"
        return Severity.MEDIUM, RecoveryAction.RETRY, False, \
               f"Build error (attempt {attempt}) — retrying"

    if failure_type == FailureType.TEST_FAILURE:
        if prod:
            return Severity.HIGH, RecoveryAction.ALERT_ONLY, escalated, \
                   "Test failure on production branch — blocking deploy"
        if escalated:
            return Severity.MEDIUM, RecoveryAction.MANUAL, True, \
                   f"Tests still failing after {attempt} attempts — manual review"
        return Severity.MEDIUM, RecoveryAction.RETRY, False, \
               f"Test failure (attempt {attempt}) — retrying"

    if failure_type == FailureType.DEPENDENCY_ERROR:
        if escalated:
            return Severity.HIGH, RecoveryAction.ALERT_ONLY, True, \
                   "Dependency error persists — registry may be down or package yanked"
        return Severity.MEDIUM, RecoveryAction.RETRY, False, \
               f"Dependency error (attempt {attempt}) — retrying"

    if failure_type == FailureType.TIMEOUT:
        if escalated:
            return Severity.HIGH, RecoveryAction.ALERT_ONLY, True, \
                   "Repeated timeouts — possible infrastructure issue"
        return Severity.MEDIUM, RecoveryAction.RESTART, False, \
               "Timeout — restarting pipeline"

    if failure_type == FailureType.CONFIG_ERROR:
        return Severity.MEDIUM, RecoveryAction.MANUAL, escalated, \
               "Config error — manual fix required"

    return Severity.MEDIUM, RecoveryAction.ALERT_ONLY, escalated, \
           "Unknown failure — alerting team for triage"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Failure classifier started")
    yield
    logger.info("Failure classifier stopped")


app = FastAPI(title="Failure Classifier", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.post("/classify", response_model=ClassifyResponse)
async def classify_endpoint(req: ClassifyRequest):
    logger.info(
        "Classify request: pipeline=%s stage=%s failure=%s attempt=%s branch=%s",
        req.pipeline_id, req.stage,
        req.analysis.failure_type, req.attempt, req.branch,
    )

    findings     = req.analysis.details or []
    failure_type = normalise_failure_type(req.analysis.failure_type, findings)
    prod         = is_production(req.branch)

    severity, recovery, escalated, reason = classify(
        failure_type, req.stage, req.attempt, prod
    )

    logger.info(
        "Classified: pipeline=%s type=%s severity=%s recovery=%s escalated=%s",
        req.pipeline_id, failure_type, severity, recovery, escalated,
    )

    return ClassifyResponse(
        pipeline_id   = req.pipeline_id,
        failure_type  = failure_type,
        severity      = severity,
        recovery      = recovery,
        is_production = prod,
        escalated     = escalated,
        reason        = reason,
        classified_at = datetime.now(timezone.utc).isoformat(),
    )


@app.get("/classify/rules")
async def get_rules():
    return {
        "rules": {
            "BUILD_ERROR":      "RETRY → ALERT_ONLY after max attempts",
            "TEST_FAILURE":     "RETRY → MANUAL (ALERT_ONLY on production)",
            "DEPLOY_ERROR":     "RETRY non-prod / ROLLBACK on production",
            "DEPENDENCY_ERROR": "RETRY → ALERT_ONLY after max attempts",
            "TIMEOUT":          "RESTART → ALERT_ONLY after max attempts",
            "CONFIG_ERROR":     "MANUAL always",
            "UNKNOWN":          "ALERT_ONLY always",
        },
        "production_branches": sorted(PROD_BRANCHES) + ["release/*"],
        "max_auto_retries":    MAX_AUTO_RETRIES,
    }


@app.get("/health")
async def health():
    return {
        "service": "failure-classifier",
        "status":  "ok",
    }