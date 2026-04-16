# CS 331 — Software Engineering Lab
## Assignment 9: Testing & Defect Analysis

---

| Field             | Details                                              |
|-------------------|------------------------------------------------------|
| **Course**        | CS 331 — Software Engineering Lab                    |
| **Assignment**    | 9 (Total Marks = 20)                                 |
| **Project Title** | CI/CD Pipeline — Automated Failure Recovery System   |
| **Repository**    | https://github.com/devkumarbaheti2507/CI-CD-Pipeline |
| **Tech Stack**    | Python 3.10+ (FastAPI, Pydantic, httpx), React.js, Redis, Jenkins, Docker |

---

## Table of Contents

1. [Q1(a) — Test Plan](#q1a--test-plan)
2. [Q1(b) — Test Case Design (8 Test Cases)](#q1b--test-case-design)
3. [Q2(a) — Test Execution Results & Evidence](#q2a--test-execution-results--evidence)
4. [Q2(b) — Defect Analysis (3 Bugs)](#q2b--defect-analysis)

---
---

## Q1(a) — Test Plan

### 1. Objective of Testing

The objective of this testing effort is to verify and validate the **CI/CD Pipeline Automated Failure Recovery System** — a microservice-based platform that intercepts CI/CD pipeline events, analyzes build/test logs for failures, classifies the type and severity of failures, triggers automated recovery actions (retry, rollback, restart), and dispatches notifications through multiple channels (email, Slack, webhook).

Testing aims to ensure:
- Each microservice functions correctly in isolation (unit-level correctness).
- Services communicate correctly with each other through REST APIs (integration correctness).
- The system handles edge cases, boundary inputs, and error conditions gracefully.
- Security mechanisms (SSRF protection, rate limiting, webhook signature verification) operate as intended.

---

### 2. Scope — Modules/Features to be Tested

The system consists of **six backend microservices** and a **React frontend dashboard**. The following modules fall within the testing scope:

| # | Module                    | Port  | Key Features to Test                                                |
|---|---------------------------|-------|---------------------------------------------------------------------|
| 1 | **Pipeline Controller**   | 9000  | Event ingestion, payload validation, rate limiting, job status tracking, Redis state management |
| 2 | **Log Analyzer**          | 5001  | Log parsing (plain/JSON/logfmt), failure rule engine, severity scoring, batch analysis |
| 3 | **Failure Classifier**    | 8000  | Classification logic, severity assignment, recovery action mapping, production branch detection |
| 4 | **Recovery Manager**      | 8001  | Recovery rule lookup, Jenkins retry/rollback/restart triggers, max-retry enforcement |
| 5 | **Notification Service**  | 7000  | Message template building, email/Slack/webhook dispatching          |
| 6 | **GitHub Webhook Adapter**| 9001  | Webhook signature verification, push event parsing, payload forwarding |

**Out of Scope:** Frontend UI testing, Jenkins job configuration, Docker container internals, third-party service reliability (Gmail SMTP, Slack API).

---

### 3. Types of Testing to be Performed

| Testing Type             | Description                                                                                       |
|--------------------------|---------------------------------------------------------------------------------------------------|
| **Unit Testing (White-box)** | Test internal functions, data models, and decision logic of each microservice without making HTTP calls. Verifies code-level correctness of classification rules, recovery mappings, message builders, and Pydantic schema validation. |
| **Integration Testing (Black-box)** | Test each microservice's REST API endpoints as a black box — send HTTP requests and verify responses. Ensures correct inter-service communication when all services are running simultaneously. |
| **Boundary Value Testing** | Test edge cases on validated input fields (e.g., `run_number = 0`, `event_id` with min/max lengths, empty payloads). |
| **Security Testing**     | Verify SSRF protections in the Pipeline Controller (blocking internal/loopback IPs), rate limiting behavior, and webhook signature verification in the GitHub Adapter. |

---

### 4. Tools

| Tool / Library           | Purpose                                              |
|--------------------------|------------------------------------------------------|
| **pytest**               | Test runner for both white-box and black-box tests   |
| **Python unittest**      | Base framework for writing structured test classes   |
| **urllib.request**       | Black-box HTTP calls to running service endpoints    |
| **Pydantic**             | Model validation testing (schema boundary checks)   |
| **Redis**                | State storage during integration tests               |
| **Docker Desktop**       | Running Redis and Jenkins containers for testing     |

---

### 5. Entry and Exit Criteria

#### Entry Criteria
- All source code compiles and runs without syntax errors.
- Python virtual environment is activated with all dependencies installed (`pip install -r requirements.txt`).
- For integration tests: All 6 backend services are running (via `scripts\start.bat`), Redis container is active on port 6379, and Jenkins container is active on port 8080.
- For unit tests: No running services are required.

#### Exit Criteria
- All planned test cases have been executed.
- Test results are documented with evidence (CLI logs / screenshots).
- All **High** and **Critical** severity defects are documented with reproduction steps.
- Overall test pass rate is ≥ 85%.

---
---

## Q1(b) — Test Case Design

**Module Selected for Detailed Testing:** Pipeline Controller (`pipeline_controller.py`, Port 9000)

The Pipeline Controller is the central orchestrator of the system. It receives pipeline events, fetches Jenkins logs, coordinates with the Log Analyzer, Recovery Manager, and Notification Service, and tracks job state in Redis. It is the most critical module for end-to-end flow.

---

### Test Cases

#### TC-01: Valid Pipeline Event Submission

| Field             | Details |
|-------------------|---------|
| **Test Case ID**  | TC-PC-01 |
| **Test Scenario** | Submit a valid pipeline event payload and verify the API accepts it with a `202 Accepted` response. |
| **Input Data**    | `POST /pipeline-event` with JSON body: `{"event_id": "evt-abcdef1234", "pipeline_id": "demo-pipeline", "run_number": 5, "status": "FAILED", "log_url": "http://localhost:8080/job/demo/1/consoleText"}` |
| **Expected Output** | HTTP `202 Accepted`; Response body contains `job_id` (UUID) and `status: "accepted"`. |
| **Actual Output** | HTTP `202 Accepted`; Response: `{"job_id": "f3a1b2c3-...", "status": "accepted"}` |
| **Status**        | ✅ **Pass** |

---

#### TC-02: Rejection of Invalid Run Number (Boundary — Zero)

| Field             | Details |
|-------------------|---------|
| **Test Case ID**  | TC-PC-02 |
| **Test Scenario** | Submit a pipeline event with `run_number: 0`. The Pydantic model uses `Field(gt=0)`, so zero must be rejected. |
| **Input Data**    | `POST /pipeline-event` with JSON body: `{"event_id": "evt-abcdef1234", "pipeline_id": "demo-pipeline", "run_number": 0, "status": "FAILED", "log_url": "http://localhost:8080/job/demo/1/consoleText"}` |
| **Expected Output** | HTTP `422 Unprocessable Entity` with validation error for `run_number`. |
| **Actual Output** | HTTP `422 Unprocessable Entity`; Error detail: `"Input should be greater than 0"`. |
| **Status**        | ✅ **Pass** |

---

#### TC-03: Rejection of Short Event ID (Boundary — Min Length)

| Field             | Details |
|-------------------|---------|
| **Test Case ID**  | TC-PC-03 |
| **Test Scenario** | Submit a pipeline event with `event_id` shorter than the required 10 characters. The model uses `StringConstraints(min_length=10)`. |
| **Input Data**    | `POST /pipeline-event` with JSON body: `{"event_id": "abc", "pipeline_id": "demo-pipeline", "run_number": 1, "status": "FAILED", "log_url": "http://localhost:8080/job/demo/1/consoleText"}` |
| **Expected Output** | HTTP `422 Unprocessable Entity` with validation error for `event_id`. |
| **Actual Output** | HTTP `422 Unprocessable Entity`; Error detail: `"String should have at least 10 characters"`. |
| **Status**        | ✅ **Pass** |

---

#### TC-04: Job Status Retrieval — Valid Job ID

| Field             | Details |
|-------------------|---------|
| **Test Case ID**  | TC-PC-04 |
| **Test Scenario** | After submitting a valid pipeline event (TC-01), query the `/pipeline-status/{job_id}` endpoint using the returned `job_id`. |
| **Input Data**    | `GET /pipeline-status/f3a1b2c3-...` (the `job_id` from TC-01). |
| **Expected Output** | HTTP `200 OK`; JSON object with fields like `status`, `pipeline_id`, `event_id`, `submitted_at`. |
| **Actual Output** | HTTP `200 OK`; JSON with `status: "completed"`, `failure_type: "TIMEOUT"`, `severity: "HIGH"`. |
| **Status**        | ✅ **Pass** |

---

#### TC-05: Job Status Retrieval — Non-Existent Job ID

| Field             | Details |
|-------------------|---------|
| **Test Case ID**  | TC-PC-05 |
| **Test Scenario** | Query `/pipeline-status/` with a UUID that does not exist in Redis. |
| **Input Data**    | `GET /pipeline-status/00000000-0000-0000-0000-000000000000` |
| **Expected Output** | HTTP `404 Not Found`; Error detail: `"Job not found"`. |
| **Actual Output** | HTTP `404 Not Found`; Detail: `"Job not found"`. |
| **Status**        | ✅ **Pass** |

---

#### TC-06: Rate Limiting Enforcement

| Field             | Details |
|-------------------|---------|
| **Test Case ID**  | TC-PC-06 |
| **Test Scenario** | Send more requests than the configured `RATE_LIMIT_PER_MINUTE` (default 100) from a single IP within 60 seconds. The 101st request should be blocked. |
| **Input Data**    | 101 consecutive `POST /pipeline-event` requests with valid payloads from the same client. |
| **Expected Output** | Requests 1–100: HTTP `202 Accepted`. Request 101: HTTP `429 Too Many Requests`. |
| **Actual Output** | Requests 1–100: `202`. Request 101: `429` with detail `"Too many requests"`. |
| **Status**        | ✅ **Pass** |

---

#### TC-07: Health Check Endpoint

| Field             | Details |
|-------------------|---------|
| **Test Case ID**  | TC-PC-07 |
| **Test Scenario** | Call the `/health` endpoint to verify the service is alive and reports the correct version. |
| **Input Data**    | `GET /health` |
| **Expected Output** | HTTP `200 OK`; JSON body: `{"status": "ok", "version": "1.0.1"}`. |
| **Actual Output** | HTTP `200 OK`; JSON body: `{"status": "ok", "version": "1.0.1"}`. |
| **Status**        | ✅ **Pass** |

---

#### TC-08: SSRF Protection — Loopback Address in Log URL

| Field             | Details |
|-------------------|---------|
| **Test Case ID**  | TC-PC-08 |
| **Test Scenario** | Submit a pipeline event where `log_url` points to a loopback/internal address (`http://127.0.0.1/secret`). The `resolve_host()` function should detect the private IP and raise `UnsafeURLError`. |
| **Input Data**    | `POST /pipeline-event` with `log_url: "http://127.0.0.1/etc/passwd"` |
| **Expected Output** | The `fetch_logs()` function should raise `UnsafeURLError`, preventing the system from making internal network requests. The job should record an error state. |
| **Actual Output** | The system **does not raise** `UnsafeURLError`. Instead, the `except httpx.RequestError` block catches the connection failure and silently falls back to `SIMULATED_LOG`, processing the hardcoded demo log as if it were real Jenkins output. |
| **Status**        | ❌ **Fail** |

---

### Test Case Summary

| Total Test Cases | Passed | Failed | Pass Rate |
|------------------|--------|--------|-----------|
| 8                | 7      | 1      | 87.5%     |

---
---

## Q2(a) — Test Execution Results & Evidence

### White-Box Test Execution (Unit Tests)

The white-box tests test internal functions and data structures directly, without making HTTP calls. They were run using:

```
cd backend
python -m pytest tests/test_whitebox.py -v
```

**Console Output:**

```
============================= test session starts ==============================
platform win32 -- Python 3.10.5, pytest-7.4.3, pluggy-1.3.0 -- C:\Users\adity\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\adity\OneDrive\Desktop\ci-cd_pipeline\backend
collected 4 items

tests/test_whitebox.py::TestAllServicesWhiteBox::test_fc_classify_build_error PASSED  [ 25%]

  [INFO] Starting White Box Test: Failure Classifier Engine
  [INFO] Invoking internal classify() method with BUILD_ERROR simulation variable...
  [INFO] Verified: Internal decision engine accurately mapped logic -> (Severity: MEDIUM, Action: RETRY) without escalation.

tests/test_whitebox.py::TestAllServicesWhiteBox::test_rm_rule_mapping PASSED          [ 50%]

  [INFO] Starting White Box Test: Recovery Manager Routing Tables
  [INFO] Auditing memory-mapped RECOVERY_RULES dictionary configuration constraints...
  [INFO] Verified: Internal memory map correctly asserts DEPENDENCY_ERROR -> RETRY and TIMEOUT -> RESTART.

tests/test_whitebox.py::TestAllServicesWhiteBox::test_ns_build_message PASSED         [ 75%]

  [INFO] Starting White Box Test: Notification Template Builder
  [INFO] Instantiating internal NotifyRequest data class and piping string structure...
  [INFO] Verified: Template engine correctly composed the abstract syntax into a strict Markdown Notification string.

tests/test_whitebox.py::TestAllServicesWhiteBox::test_pc_pydantic_validation PASSED   [100%]

  [INFO] Starting White Box Test: Pipeline Controller Pydantic Schemas
  [INFO] Mapping raw Python dictionary onto PipelineEvent object model class...
  [INFO] Pass! Data model cleanly type-casted valid datatypes.
  [INFO] Simulating core memory corruption via negative bound logic exception...
  [INFO] Verified: Internal structural schema constraints threw ValueError before payload reached deeper app layers.

============================== 4 passed in 0.38s ===============================
```

**Observations:**
- `classify()` correctly maps `BUILD_ERROR` at attempt 1 to `Severity.MEDIUM` with `RecoveryAction.RETRY`.
- `RECOVERY_RULES` dict correctly maps `DEPENDENCY_ERROR → RETRY` and `TIMEOUT → RESTART`.
- `build_message()` correctly injects `❌` for `FAILED` status and `Triggered` text when recovery is active.
- `PipelineEvent` Pydantic model correctly rejects `run_number = -5` with a `ValueError`.

---

### Black-Box Test Execution (Integration Tests)

The black-box tests hit live running service endpoints. All 6 backend services and Redis/Jenkins containers must be running. They were run using:

```
cd backend
python -m pytest tests/test_blackbox.py -v
```

**Console Output:**

```
============================= test session starts ==============================
platform win32 -- Python 3.10.5, pytest-7.4.3, pluggy-1.3.0 -- C:\Users\adity\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\adity\OneDrive\Desktop\ci-cd_pipeline\backend
collected 4 items

tests/test_blackbox.py::TestAllServicesBlackBox::test_fc_classify_endpoint PASSED     [ 25%]

  [INFO] Starting Black Box Test: Failure Classifier (Port 8000)
  [INFO] Sending POST http://localhost:8000/classify with mock DEPLOY_ERROR payload on 'main' branch...
  [INFO] Success! Received HTTP 200 OK. Response data: {'pipeline_id': 'test-box', 'failure_type': 'DEPLOY_ERROR', 'severity': 'CRITICAL', 'recovery': 'ROLLBACK', 'is_production': True, 'escalated': False, 'reason': 'Deploy failed on production — rollback triggered', ...}
  [INFO] Verified: System securely triggered a ROLLBACK for production deployment error.

tests/test_blackbox.py::TestAllServicesBlackBox::test_rm_recover_endpoint PASSED      [ 50%]

  [INFO] Starting Black Box Test: Recovery Manager (Port 8001)
  [INFO] Sending POST http://localhost:8001/recover requesting automatic recovery for generic TEST_FAILURE...
  [INFO] Success! Received HTTP 200 OK. Response data: {'pipeline_id': 'test-box', 'failure_type': 'TEST_FAILURE', 'action_taken': 'RETRY', 'success': True, ...}
  [INFO] Verified: System correctly assigned RETRY strategy.

tests/test_blackbox.py::TestAllServicesBlackBox::test_ns_notify_endpoint PASSED       [ 75%]

  [INFO] Starting Black Box Test: Notification Service (Port 7000)
  [INFO] Sending POST http://localhost:7000/notify to dispatch notification for successful pipeline...
  [INFO] Success! Received HTTP 200 OK. Response data: {'status': 'ok', 'pipeline_id': 'test-notify-id', 'channels': {'email': False, 'slack': False, 'webhook': False}, 'any_sent': False, ...}
  [INFO] Verified: Notification dispatched accurately without crashing.

tests/test_blackbox.py::TestAllServicesBlackBox::test_pc_pipeline_event_endpoint_boundary PASSED [100%]

  [INFO] Starting Black Box Test: Pipeline Controller Boundary Security (Port 9000)
  [INFO] Intentionally sending MALFORMED POST to http://localhost:9000/pipeline-event to test Validation framework vulnerabilities...
  [INFO] Pass! API successfully blocked the bad request and threw HTTP 422 Unprocessable Entity.

============================== 4 passed in 2.14s ===============================
```

**Observations:**
- Failure Classifier correctly classifies `DEPLOY_ERROR` on `main` branch as `CRITICAL` severity with `ROLLBACK` recovery.
- Recovery Manager correctly maps `TEST_FAILURE` to `RETRY` action.
- Notification Service processes the request without crashing even with all channels disabled.
- Pipeline Controller correctly rejects malformed payloads with `422 Unprocessable Entity`.

---

### Pipeline Controller Endpoint Tests (Manual / TC-01 through TC-08)

**TC-01 through TC-07 (Pass):**

```
> curl -X POST http://localhost:9000/pipeline-event -H "Content-Type: application/json" \
  -d '{"event_id":"evt-abcdef1234","pipeline_id":"demo-pipeline","run_number":5,"status":"FAILED","log_url":"http://localhost:8080/job/demo/1/consoleText"}'

< HTTP/1.1 202 Accepted
< {"job_id":"f3a1b2c3-d4e5-6789-abcd-ef0123456789","status":"accepted"}
```

```
> curl http://localhost:9000/health

< HTTP/1.1 200 OK
< {"status":"ok","version":"1.0.1"}
```

```
> curl http://localhost:9000/pipeline-status/00000000-0000-0000-0000-000000000000

< HTTP/1.1 404 Not Found
< {"detail":"Job not found"}
```

**TC-08 (Fail) — SSRF Log:**

```
> curl -X POST http://localhost:9000/pipeline-event -H "Content-Type: application/json" \
  -d '{"event_id":"evt-ssrf-test01","pipeline_id":"ssrf-test","run_number":1,"status":"FAILED","log_url":"http://127.0.0.1/etc/passwd"}'

< HTTP/1.1 202 Accepted
< {"job_id":"...","status":"accepted"}

--- Pipeline Controller Service Log ---
2026-04-16 17:30:12 [WARNING] Jenkins unreachable (ConnectError) — using simulated log for demo
2026-04-16 17:30:12 [INFO] Processing with SIMULATED_LOG fallback...
```

The SSRF protection in `resolve_host()` was bypassed because the `except httpx.RequestError` handler caught the connection error **before** the `UnsafeURLError` check could trigger, silently falling back to demo mode.

---
---

## Q2(b) — Defect Analysis

### Bug 1: SSRF Protection Bypassed by Silent Fallback to Simulated Log

| Field               | Details |
|----------------------|---------|
| **Bug ID**           | BUG-001 |
| **Description**      | The Pipeline Controller's `fetch_logs()` function is designed to prevent Server-Side Request Forgery (SSRF) by checking if a `log_url` resolves to a private/loopback IP via the `resolve_host()` function. However, when the connection to a loopback address fails (since no server is listening), the `except httpx.RequestError` catch block silently intercepts the error and returns a hardcoded `SIMULATED_LOG` string. This means the SSRF guard never actually blocks the request — the system processes the demo log as if it were real Jenkins output. |
| **Steps to Reproduce** | 1. Start all backend services via `scripts\start.bat`. <br> 2. Send `POST /pipeline-event` with `log_url` set to `http://127.0.0.1/etc/passwd`. <br> 3. Observe the service log — it shows `"Jenkins unreachable — using simulated log for demo"` instead of blocking the request. <br> 4. Check `/pipeline-status/{job_id}` — the job completes successfully with analysis results from the simulated log. |
| **Expected Result**  | The `resolve_host()` function should detect `127.0.0.1` as a loopback IP and raise `UnsafeURLError`. The pipeline event should be marked as `"failed"` with error `"SSRF blocked: log_url resolved to restricted IP"`. |
| **Actual Result**    | The `UnsafeURLError` is never raised. The `httpx.RequestError` exception handler in `fetch_logs()` catches the connection failure first and returns `SIMULATED_LOG`, allowing the pipeline to complete normally. |
| **Severity**         | 🔴 **High** |
| **Suggested Fix**    | Move the `resolve_host()` call and its `UnsafeURLError` check **before** the `httpx` stream call, and do **not** catch `UnsafeURLError` in the `except` block. Additionally, introduce an environment variable `DEMO_MODE=true/false` to control whether the simulated log fallback is allowed: |

```python
# Suggested fix in fetch_logs():
async def fetch_logs(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # SSRF check MUST happen before any network call
    try:
        ip = await resolve_host(hostname)
    except UnsafeURLError:
        raise  # Let it propagate — do NOT catch this

    # ... rest of fetch logic ...
    try:
        async with app.state.http.stream(...) as resp:
            ...
    except httpx.RequestError as exc:
        if DEMO_MODE:
            return SIMULATED_LOG
        raise  # In production, propagate the error
```

---

### Bug 2: Rate Limiter Breaks Under Reverse Proxy (ngrok)

| Field               | Details |
|----------------------|---------|
| **Bug ID**           | BUG-002 |
| **Description**      | The Pipeline Controller's rate limiter extracts the client IP using `request.client.host`. When the service is exposed through `ngrok` (or any reverse proxy), all incoming requests appear to come from `127.0.0.1` (the proxy's local address). This means the rate limit counter is shared across **all external users**, causing legitimate users to be blocked after as few as 100 total requests from any user combined. |
| **Steps to Reproduce** | 1. Start all services and expose port 9000 via `ngrok http 9000`. <br> 2. From **User A's** machine, send 60 valid `POST /pipeline-event` requests. <br> 3. From **User B's** machine (different IP), send 50 valid requests. <br> 4. User B's 41st request (total = 101) returns `429 Too Many Requests`, even though User B has only sent 50 requests. |
| **Expected Result**  | Each distinct external IP should have its own rate limit counter. User A gets 100 requests/minute and User B also gets 100 requests/minute independently. |
| **Actual Result**    | All external requests are attributed to `127.0.0.1` (ngrok's bridge IP). The 101st request from **any** user gets blocked. |
| **Severity**         | 🔴 **High** |
| **Suggested Fix**    | Read the client IP from the `X-Forwarded-For` header (set by ngrok and most reverse proxies) instead of `request.client.host`: |

```python
# Current code (line 329):
client_ip = request.client.host if request.client else "unknown"

# Suggested fix:
forwarded = request.headers.get("X-Forwarded-For", "")
client_ip = forwarded.split(",")[0].strip() if forwarded else (
    request.client.host if request.client else "unknown"
)
```

---

### Bug 3: GitHub Adapter Webhook Signature Uses `hmac.new()` Instead of `hmac.new()` — Incorrect API Call

| Field               | Details |
|----------------------|---------|
| **Bug ID**           | BUG-003 |
| **Description**      | In `github_adapter.py`, the `verify_signature()` function uses `hmac.new()` to compute the HMAC digest. However, Python's `hmac` module does not have a `.new()` function — the correct function is `hmac.new()` (this is technically valid but the code on line 25 uses it as a method call that will work). The **real issue** is that when `WEBHOOK_SECRET` is empty (the default), the function returns `True` unconditionally, meaning **any** payload from any source is accepted without verification. This allows any attacker to send forged webhook events to the adapter. |
| **Steps to Reproduce** | 1. Start the GitHub Adapter service with the default `.env` (where `GITHUB_WEBHOOK_SECRET` is empty). <br> 2. Send a `POST /pipeline-event` request to `localhost:9001` with an arbitrary JSON body and **no** `X-Hub-Signature-256` header. <br> 3. The request is accepted and forwarded to the Pipeline Controller. |
| **Expected Result**  | When no `GITHUB_WEBHOOK_SECRET` is configured, the adapter should either: (a) refuse all requests with a configuration error, or (b) log a prominent security warning on every request. |
| **Actual Result**    | All requests are silently accepted. The `verify_signature()` function returns `True` immediately when `secret` is empty (line 23–24), providing zero authentication. |
| **Severity**         | 🟡 **Medium** |
| **Suggested Fix**    | Add a startup warning and optionally reject requests when no secret is configured: |

```python
# At service startup:
if not WEBHOOK_SECRET:
    import warnings
    warnings.warn(
        "GITHUB_WEBHOOK_SECRET is not set! "
        "All incoming webhooks will be accepted WITHOUT verification. "
        "This is a SECURITY RISK in production.",
        stacklevel=2,
    )

# In verify_signature():
def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not secret:
        logger.warning("Webhook accepted WITHOUT signature verification (no secret configured)")
        return True  # Still allow in dev, but log prominently
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

---
---

### Defect Summary Table

| Bug ID   | Module              | Description                                  | Severity   | Status       |
|----------|---------------------|----------------------------------------------|------------|--------------|
| BUG-001  | Pipeline Controller | SSRF protection bypassed by silent fallback   | 🔴 High    | Open         |
| BUG-002  | Pipeline Controller | Rate limiter shares state behind proxy        | 🔴 High    | Open         |
| BUG-003  | GitHub Adapter      | Webhook auth disabled when secret is empty    | 🟡 Medium  | Open         |

---
---

## Conclusion

- A total of **8 test cases** were designed for the Pipeline Controller module, covering valid submissions, boundary validation, error handling, rate limiting, health checks, and security (SSRF).
- **7 out of 8** test cases passed, yielding an **87.5% pass rate**.
- **3 defects** were identified and documented with full reproduction steps, expected vs. actual results, severity classification, and suggested code fixes.
- The white-box unit tests (4 tests) and black-box integration tests (4 tests) all passed successfully, confirming that the core classification, recovery, and notification logic is functioning correctly.

---

*End of Assignment 9*
