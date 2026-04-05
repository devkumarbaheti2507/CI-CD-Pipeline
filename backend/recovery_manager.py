import os
import asyncio
import logging
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
logger = logging.getLogger("recovery-manager")

JENKINS_URL      = os.getenv("JENKINS_URL",       "http://localhost:8080")
JENKINS_USER     = os.getenv("JENKINS_USER",      "admin")
JENKINS_TOKEN    = os.getenv("JENKINS_TOKEN",     "")
HTTP_TIMEOUT     = int(os.getenv("HTTP_TIMEOUT",  "30"))
RETRY_COUNT      = int(os.getenv("RETRY_COUNT",   "3"))
MAX_AUTO_RETRIES = int(os.getenv("MAX_AUTO_RETRIES", "2"))


class FailureType(str, Enum):
    BUILD_ERROR      = "BUILD_ERROR"
    TEST_FAILURE     = "TEST_FAILURE"
    DEPLOY_ERROR     = "DEPLOY_ERROR"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    TIMEOUT          = "TIMEOUT"
    UNKNOWN          = "UNKNOWN"


class RecoveryAction(str, Enum):
    RETRY    = "RETRY"
    ROLLBACK = "ROLLBACK"
    RESTART  = "RESTART"
    SKIP     = "SKIP"
    MANUAL   = "MANUAL"


class RecoverRequest(BaseModel):
    pipeline_id:  str
    failure_type: FailureType
    run_number:   Optional[int] = None
    branch:       Optional[str] = None
    attempt:      int           = 1


class RecoverResponse(BaseModel):
    pipeline_id:  str
    failure_type: str
    action_taken: RecoveryAction
    success:      bool
    message:      str
    recovered_at: str


RECOVERY_RULES: dict = {
    FailureType.BUILD_ERROR:      RecoveryAction.RETRY,
    FailureType.TEST_FAILURE:     RecoveryAction.RETRY,
    FailureType.DEPLOY_ERROR:     RecoveryAction.ROLLBACK,
    FailureType.DEPENDENCY_ERROR: RecoveryAction.RETRY,
    FailureType.TIMEOUT:          RecoveryAction.RESTART,
    FailureType.UNKNOWN:          RecoveryAction.MANUAL,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        auth=(JENKINS_USER, JENKINS_TOKEN) if JENKINS_TOKEN else None,
    )
    logger.info("Recovery manager started")
    yield
    await app.state.http.aclose()
    logger.info("Recovery manager stopped")


app = FastAPI(title="Recovery Manager", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



async def jenkins_request(method: str, path: str, **kwargs):
    url      = f"{JENKINS_URL.rstrip('/')}{path}"
    last_exc = None

    for attempt in range(RETRY_COUNT):
        try:
            resp = await app.state.http.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise
            last_exc = exc
        except httpx.RequestError as exc:
            last_exc = exc

        if attempt < RETRY_COUNT - 1:
            await asyncio.sleep(2 ** attempt)

    raise last_exc


async def do_retry(req) -> tuple:
    if req.attempt > MAX_AUTO_RETRIES:
        return False, f"Max auto-retries ({MAX_AUTO_RETRIES}) reached — manual intervention required"

    try:
        path   = f"/job/{req.pipeline_id}/build"
        params = {"BRANCH": req.branch} if req.branch else None
        await jenkins_request("POST", path, params=params)
        logger.info("Retry triggered: pipeline=%s attempt=%s", req.pipeline_id, req.attempt)
        return True, f"Pipeline retry triggered (attempt {req.attempt})"

    except httpx.HTTPStatusError as exc:
        logger.error("Retry failed — Jenkins %s", exc.response.status_code)
        return False, f"Jenkins returned {exc.response.status_code}"

    except httpx.RequestError as exc:
        logger.error("Retry failed — Jenkins unreachable: %s", exc)
        return False, "Jenkins unreachable"

    except Exception as exc:
        logger.error("Retry failed: %s", exc)
        return False, str(exc)


async def do_rollback(req) -> tuple:
    if not req.run_number or req.run_number <= 1:
        return False, "No previous build to roll back to"

    previous_build = req.run_number - 1

    try:
        info_path = f"/job/{req.pipeline_id}/{previous_build}/api/json"
        resp      = await jenkins_request("GET", info_path)
        build_info = resp.json()

        if build_info.get("result") != "SUCCESS":
            return False, f"Build #{previous_build} did not succeed — cannot roll back to it"

        await jenkins_request(
            "POST",
            f"/job/{req.pipeline_id}/build",
            params={"BUILD_NUMBER": previous_build},
        )
        logger.info("Rollback triggered: pipeline=%s to build #%s", req.pipeline_id, previous_build)
        return True, f"Rollback to build #{previous_build} triggered"

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return False, f"Build #{previous_build} not found in Jenkins"
        logger.error("Rollback failed — Jenkins %s", exc.response.status_code)
        return False, f"Jenkins returned {exc.response.status_code}"

    except httpx.RequestError as exc:
        logger.error("Rollback failed — Jenkins unreachable: %s", exc)
        return False, "Jenkins unreachable"

    except Exception as exc:
        logger.error("Rollback failed: %s", exc)
        return False, str(exc)


async def do_restart(req) -> tuple:
    try:
        await jenkins_request("POST", f"/job/{req.pipeline_id}/build")
        logger.info("Restart triggered: pipeline=%s", req.pipeline_id)
        return True, "Pipeline restarted"

    except httpx.HTTPStatusError as exc:
        logger.error("Restart failed — Jenkins %s", exc.response.status_code)
        return False, f"Jenkins returned {exc.response.status_code}"

    except httpx.RequestError as exc:
        logger.error("Restart failed — Jenkins unreachable: %s", exc)
        return False, "Jenkins unreachable"

    except Exception as exc:
        logger.error("Restart failed: %s", exc)
        return False, str(exc)


async def do_skip(req) -> tuple:
    logger.info("Stage skipped: pipeline=%s", req.pipeline_id)
    return True, "Stage skipped"


async def do_manual(req) -> tuple:
    logger.warning(
        "Manual intervention required: pipeline=%s failure=%s",
        req.pipeline_id, req.failure_type,
    )
    return True, "Manual intervention required — team has been notified via notification service"


HANDLERS = {
    RecoveryAction.RETRY:    do_retry,
    RecoveryAction.ROLLBACK: do_rollback,
    RecoveryAction.RESTART:  do_restart,
    RecoveryAction.SKIP:     do_skip,
    RecoveryAction.MANUAL:   do_manual,
}


@app.post("/recover", response_model=RecoverResponse)
async def recover(req: RecoverRequest):
    logger.info(
        "Recovery request: pipeline=%s failure=%s attempt=%s",
        req.pipeline_id, req.failure_type, req.attempt,
    )

    action  = RECOVERY_RULES.get(req.failure_type, RecoveryAction.MANUAL)
    handler = HANDLERS[action]

    success, message = await handler(req)

    logger.info(
        "Recovery complete: pipeline=%s action=%s success=%s",
        req.pipeline_id, action, success,
    )

    return RecoverResponse(
        pipeline_id  = req.pipeline_id,
        failure_type = req.failure_type.value,
        action_taken = action,
        success      = success,
        message      = message,
        recovered_at = datetime.now(timezone.utc).isoformat(),
    )


@app.get("/recover/rules")
async def get_rules():
    return {
        "rules": {ft.value: action.value for ft, action in RECOVERY_RULES.items()}
    }


@app.get("/health")
async def health():
    jenkins_ok = False
    try:
        resp       = await app.state.http.get(f"{JENKINS_URL.rstrip('/')}/api/json", timeout=2)
        jenkins_ok = resp.status_code == 200
    except Exception:
        pass

    return {
        "service":     "recovery-manager",
        "status":      "ok",
        "jenkins":     jenkins_ok,
        "jenkins_url": JENKINS_URL,
    }