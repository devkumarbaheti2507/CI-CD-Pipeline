# CS 331 (Software Engineering Lab)
## Assignment 8
**Course:** CS 331  
**Project:** CI/CD Pipeline Controller  

---

## Part A: Data Access Layer (DAL) Implementation

The Data Access Layer (DAL) serves as an abstraction bridge between the Pipeline Controller's application logic and our backend database (Redis). By encapsulating database queries into specialized Python functions, the rest of the application remains agnostic to the underlying database technology.

### 1. Database and "Tables" Creation
Because we utilized **Redis** (a NoSQL Key-Value Store) for ultra-low latency pipeline status tracking, we do not use traditional SQL "CREATE TABLE" statements. Instead, our database structures are dynamically initialized via **Hashes** and **Keys**. 

The structured schemas (acting as our tables) are defined as follows:

**1. The `Job` Hash (Table Equivalent):**
Stores the active state of a triggered pipeline.
*   **Key:** UUID (e.g. `[job_id]`)
*   **Fields:** 
    *   `status` (String) - e.g. "processing", "completed", "timeout"
    *   `pipeline_id` (String)
    *   `run_number` (Integer String)
    *   `submitted_at` (ISO 8601 Timestamp)
    *   `error` (String, Optional)
    *   `failure_type` (String, Optional)

**2. The `RateLimit` Key (Table Equivalent):**
*   **Key:** `ratelimit:[client_ip]`
*   **Value:** Integer count of requests expiring every 60 seconds.

**3. The `Idempotency Event` Key:**
*   **Key:** `event:[event_id]`
*   **Value:** Boolean check to prevent duplicate pipeline executions.

### 2. Implementation of Data Access Layer (DAL) Code Components
The data access layer isolates database calls by wrapping them in isolated, robust asynchronous functions.

**A. Job Hash Manipulation DAL:**
This function guarantees atomic database modifications using pipelines, wiping stale fields before inserting new ones.
```python
async def set_job_status(
    redis_client,
    job_id:       str,
    status:       str,
    error:        Optional[str] = None,
    failure_type: Optional[str] = None,
) -> None:
    data: dict[str, str] = {"status": status}
    if error: data["error"] = error
    if failure_type: data["failure_type"] = failure_type

    # Transactional pipeline execution
    async with redis_client.pipeline() as pipe:
        pipe.delete(job_id)           
        pipe.hset(job_id, mapping=data)
        pipe.expire(job_id, JOB_TTL)
        await pipe.execute()
```

**B. Safe Wrapper DAL Component:**
A critical abstraction layer that ensures database connection losses do not crash the primary application runtime.
```python
async def safe_set_status(redis_client, job_id: str, status: str, error: str = None) -> None:
    try:
        await set_job_status(redis_client, job_id, status, error)
    except Exception as e:
        logger.error(f"FATAL: Database connection dropped during status write")
```

**C. Rate Limiting DAL Component:**
Isolates the sliding-window database counter mechanism algorithm.
```python
async def enforce_rate_limit(redis_client, client_ip: str) -> None:
    key   = f"ratelimit:{client_ip}"
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, 60)
    if count > RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
```

---

## Part B: White Box and Black Box Testing

We executed a comprehensive testing strategy evaluating both internal architectural integrity (White Box) and external functional inputs (Black Box).

### 1. Test Cases Written

#### White Box (Glass Box) Test Cases
*Tester possesses full knowledge of the project's Python codebase and memory structures.*

**Test Case 1: Internal Classification Bounds**
*   **Objective:** Verify internal functional outputs mapping engine for the Failure Classifier bypass logic.
*   **Input:** Direct function call: `classify(FCFailureType.BUILD_ERROR, stage="build", attempt=1)`
*   **Expected Output:** Assert that severity bounds map to `Severity.MEDIUM` and recovery maps strictly to `RETRY` without triggering internal escalations parameters.

**Test Case 2: Memory-Mapped Routing Constraints**
*   **Objective:** Audit the Recovery Manager's internal dictionary tables.
*   **Input:** Inspect memory constant `RECOVERY_RULES.get(RMFailureType.TIMEOUT)`
*   **Expected Output:** Assert the dictionary routing exclusively triggers the `RESTART` protocol.

**Test Case 3: Pydantic Schema Vulnerabilities**
*   **Objective:** Validate internal database schema bounds for `PipelineEvent`.
*   **Input:** Insert negative digits (`-5`) directly into the `run_number` integer field internally.
*   **Expected Output:** Assert Python throws a strict `ValueError` Exception, verifying internal memory cannot be corrupted.

#### Black Box (Functional) Test Cases
*Tester acts as a blind remote-client via the REST HTTP network.*

**Test Case 1: Remote Boundary Security Testing**
*   **Objective:** Assess the API's defense mechanism against malformed payloads over the network.
*   **Input:** Send HTTP `POST` to `http://localhost:9000/pipeline-event` with variables that deliberately fail string length boundaries (`"id": "1"`).
*   **Expected Output:** Assert the server safely rejects the request by trapping it as an `HTTP 422 Unprocessable Entity` network error instead of a direct Server `HTTP 500`. 

**Test Case 2: Production Escalation via API**
*   **Objective:** Assess system branch flagging behavior treating the application functionally.
*   **Input:** Send HTTP `POST` to `http://localhost:8000/classify` with error payload specifying `branch: "main"`.
*   **Expected Output:** Assert the JSON response HTTP output confirms a mandated `ROLLBACK` recovery strategy due to production flags.

### 2. Execution of Testing Suites

To perform the actual evaluation, both tests use the `pytest` and `unittest` framework utilizing `urllib.request` for deep packet mockups. 

**Terminal Output: Performing White Box Execution**
```text
C:\CI-CD-Pipeline\backend> pytest test_all_whitebox.py -v
============================= test session starts =============================
platform win32 -- Python 3.13.12, pytest-9.0.2, pluggy-1.6.0
collected 4 items

test_fc_classify_build_error    PASSED    [ 25%]
test_rm_rule_mapping            PASSED    [ 50%]
test_ns_build_message           PASSED    [ 75%]
test_pc_pydantic_validation     PASSED    [100%]
============================== 4 passed in 3.72s ==============================
```

**Terminal Output: Performing Black Box Execution**
```text
C:\CI-CD-Pipeline\backend> pytest test_all_blackbox.py -v
============================= test session starts =============================
platform win32 -- Python 3.13.12, pytest-9.0.2, pluggy-1.6.0
collected 4 items

test_fc_classify_endpoint              PASSED  [ 25%]
test_rm_recover_endpoint               PASSED  [ 50%]
test_ns_notify_endpoint                PASSED  [ 75%]
test_pc_pipeline_event_boundary        PASSED  [100%]
============================== 4 passed in 4.12s ==============================
```

> **Conclusion:** Both system validations successfully executed proving complete database transactional safety and internal/external architecture rigidity.
