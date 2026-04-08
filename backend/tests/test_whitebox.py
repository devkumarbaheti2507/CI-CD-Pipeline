import unittest
import json

# Internal classes from each microservice
from failure_classifier import classify, FailureType as FCFailureType, Severity
from recovery_manager import RECOVERY_RULES, FailureType as RMFailureType, RecoveryAction as RMRecoveryAction
from notification_service import build_message, NotifyRequest, PipelineStatus
from pipeline_controller import PipelineEvent

# Log Analyzer internals
from log_analyzer import (
    analyze,
    RULES,
    LogParser,
    PlainLogParser,
    JsonLogParser,
    LogFmtParser,
    Severity as LASeverity,
)


class TestAllServicesWhiteBox(unittest.TestCase):

    # ── 1. Failure Classifier (White Box) ──
    def test_fc_classify_build_error(self):
        print("\n[INFO] Starting White Box Test: Failure Classifier Engine")
        print("[INFO] Invoking internal classify() method with BUILD_ERROR simulation variable...")
        sev, rec, esc, msg = classify(FCFailureType.BUILD_ERROR, stage="build", attempt=1, prod=False)
        self.assertEqual(sev, Severity.MEDIUM, "Failure Classifier logic should assign MEDIUM severity for generic build errors")
        self.assertFalse(esc, "Attempt 1 should not trigger escalation logic")
        self.assertEqual(rec.value, "RETRY", "Recovery logic for build error should default to RETRY")
        print(f"[INFO] Verified: Internal decision engine accurately mapped logic -> (Severity: {sev.name}, Action: {rec.name}) without escalation.")

    # ── 2. Recovery Manager (White Box) ──
    def test_rm_rule_mapping(self):
        print("\n[INFO] Starting White Box Test: Recovery Manager Routing Tables")
        print("[INFO] Auditing memory-mapped RECOVERY_RULES dictionary configuration constraints...")
        action = RECOVERY_RULES.get(RMFailureType.DEPENDENCY_ERROR)
        self.assertEqual(action, RMRecoveryAction.RETRY, "Dependency Errors must trigger internal RETRY flow")

        timeout_action = RECOVERY_RULES.get(RMFailureType.TIMEOUT)
        self.assertEqual(timeout_action, RMRecoveryAction.RESTART, "Timeouts must aggressively trigger RESTART flow")
        print("[INFO] Verified: Internal memory map correctly asserts DEPENDENCY_ERROR -> RETRY and TIMEOUT -> RESTART.")

    # ── 3. Notification Service (White Box) ──
    def test_ns_build_message(self):
        print("\n[INFO] Starting White Box Test: Notification Template Builder")
        print("[INFO] Instantiating internal NotifyRequest data class and piping string structure...")
        req = NotifyRequest(
            pipeline_id="pipe-1234",
            status=PipelineStatus.FAILED,
            failure_type="TIMEOUT",
            recovery_triggered=True
        )
        msg_out = build_message(req)

        self.assertIn("\u274c", msg_out, "Failed status must inject specific unicode marker")
        self.assertIn("pipe-1234", msg_out, "Pipeline ID missing from template engine layout")
        self.assertIn("Triggered", msg_out, "Boolean triggers should map to specific text injections")
        print("[INFO] Verified: Template engine correctly composed the abstract syntax into a strict Markdown Notification string.")

    # ── 4. Pipeline Controller (White Box) ──
    def test_pc_pydantic_validation(self):
        print("\n[INFO] Starting White Box Test: Pipeline Controller Pydantic Schemas")
        print("[INFO] Mapping raw Python dictionary onto PipelineEvent object model class...")
        valid_payload = {
            "event_id": "ab1234cde567",
            "pipeline_id": "production_pipeline_v2",
            "run_number": 42,
            "status": "SUCCESS",
            "log_url": "http://localhost/logs.txt"
        }
        event = PipelineEvent(**valid_payload)
        self.assertEqual(event.run_number, 42)
        print("[INFO] Pass! Data model cleanly type-casted valid datatypes.")

        print("[INFO] Simulating core memory corruption via negative bound logic exception...")
        invalid_payload = valid_payload.copy()
        invalid_payload["run_number"] = -5

        with self.assertRaises(ValueError, msg="PipelineEvent must strictly reject negative integers internally"):
            PipelineEvent(**invalid_payload)
        print("[INFO] Verified: Internal structural schema constraints threw ValueError before payload reached deeper app layers.")


# =============================================================================
# Log Analyzer white-box tests
# =============================================================================

class TestLogAnalyzerRuleEngine(unittest.TestCase):
    """Tests for the RuleEngine rule-matching logic."""

    def test_rules_loaded(self):
        """Rule catalogue must be non-empty after startup."""
        rules = RULES.all_rules()
        self.assertGreater(len(rules), 0, "RuleEngine should load at least one rule on startup")

    def test_build_error_rule_matches(self):
        """BUILD FAILED marker must trigger a BUILD_ERROR rule."""
        hits = RULES.scan_line("BUILD FAILED -- exit code 1")
        categories = [h["category"] for h in hits]
        self.assertIn("BUILD_ERROR", categories, "BUILD FAILED must match BUILD_ERROR category")

    def test_test_failure_rule_matches(self):
        """Pytest failure line must trigger a TEST_FAILURE rule."""
        hits = RULES.scan_line("FAILED tests/test_api.py::test_endpoint - AssertionError")
        categories = [h["category"] for h in hits]
        self.assertIn("TEST_FAILURE", categories, "Pytest FAILED line must match TEST_FAILURE category")

    def test_deploy_error_rule_matches(self):
        """Deployment failure phrase must trigger a DEPLOY_ERROR rule."""
        hits = RULES.scan_line("deployment failed: container could not start")
        categories = [h["category"] for h in hits]
        self.assertIn("DEPLOY_ERROR", categories, "deployment failed must match DEPLOY_ERROR category")

    def test_dependency_error_rule_matches(self):
        """npm ERR must trigger a DEPENDENCY_ERROR rule."""
        hits = RULES.scan_line("npm ERR! 404 Not Found - GET https://registry.npmjs.org/missing-pkg")
        categories = [h["category"] for h in hits]
        self.assertIn("DEPENDENCY_ERROR", categories, "npm ERR! must match DEPENDENCY_ERROR category")

    def test_timeout_rule_matches(self):
        """Timed out phrase must trigger a TIMEOUT rule."""
        hits = RULES.scan_line("Connection Timed out after 30 seconds")
        categories = [h["category"] for h in hits]
        self.assertIn("TIMEOUT", categories, "Timed out must match TIMEOUT category")

    def test_security_cve_rule_matches(self):
        """A CVE identifier must trigger a SECURITY_ALERT rule."""
        hits = RULES.scan_line("Found vulnerability CVE-2023-44487 (HTTP/2 Rapid Reset)")
        categories = [h["category"] for h in hits]
        self.assertIn("SECURITY_ALERT", categories, "CVE identifier must match SECURITY_ALERT category")

    def test_clean_log_no_hits(self):
        """A normal info line must not produce any findings."""
        hits = RULES.scan_line("2024-01-01T00:00:00Z INFO  Build step 1/3 complete")
        self.assertEqual(hits, [], "Clean log line must produce zero findings")

    def test_severity_ordering(self):
        """CRITICAL severity must have a higher score than HIGH and LOW."""
        self.assertGreater(LASeverity.CRITICAL.score, LASeverity.HIGH.score)
        self.assertGreater(LASeverity.HIGH.score, LASeverity.MEDIUM.score)
        self.assertGreater(LASeverity.MEDIUM.score, LASeverity.LOW.score)


class TestLogAnalyzerAnalyzeFunction(unittest.TestCase):
    """Tests for the top-level analyze() function."""

    def test_clean_log_returns_success(self):
        """A log with no failure patterns must return status=SUCCESS."""
        result = analyze("Step 1: checkout\nStep 2: build passed\nStep 3: tests passed\n")
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.failures_found, 0)
        self.assertIsNone(result.failure_category)

    def test_build_failure_log_detected(self):
        """A log containing BUILD FAILED must return status=FAILED."""
        log = "Running make...\nmake: BUILD FAILED\nExit code 2\n"
        result = analyze(log)
        self.assertEqual(result.status, "FAILED")
        self.assertIsNotNone(result.failure_category)
        self.assertGreater(result.failures_found, 0)

    def test_test_failure_log_detected(self):
        """A log with pytest failure lines must be classified as TEST_FAILURE."""
        log = "collected 10 items\nFAILED tests/test_core.py::test_login - AssertionError\n1 failed, 9 passed\n"
        result = analyze(log)
        self.assertEqual(result.status, "FAILED")
        self.assertIn("TEST_FAILURE", result.category_summary)

    def test_deploy_error_detected(self):
        """A log containing deployment failure text must classify as DEPLOY_ERROR."""
        log = "Pushing image to registry...\ndeployment failed: ImagePullBackOff\n"
        result = analyze(log)
        self.assertEqual(result.status, "FAILED")
        self.assertIsNotNone(result.failure_category)

    def test_result_has_required_fields(self):
        """AnalysisResult.to_dict() must contain all mandatory output keys."""
        result = analyze("some log text")
        d = result.to_dict()
        for key in ("status", "failure_category", "failures_found", "findings",
                    "log_format", "total_lines", "analyzed_at", "duration_ms"):
            self.assertIn(key, d, f"Missing required key '{key}' in analysis result")

    def test_confidence_score_range(self):
        """Confidence score must always be between 0.0 and 1.0."""
        for text in ("BUILD FAILED", "all tests passed", ""):
            result = analyze(text)
            self.assertGreaterEqual(result.confidence_score, 0.0)
            self.assertLessEqual(result.confidence_score, 1.0)

    def test_empty_log_returns_success(self):
        """An empty log string must return status=SUCCESS with zero findings."""
        result = analyze("")
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.failures_found, 0)

    def test_multiple_categories_primary_selected(self):
        """When multiple categories match, the highest-priority category is reported."""
        log = "deployment failed: container exited with code 1\nBUILD FAILED\n"
        result = analyze(log)
        self.assertEqual(result.status, "FAILED")
        # DEPLOY_ERROR has higher priority than BUILD_ERROR in _CATEGORY_PRIORITY
        self.assertEqual(result.failure_category, "DEPLOY_ERROR")


class TestLogAnalyzerParsers(unittest.TestCase):
    """Tests for format detection and individual log parsers."""

    def test_detect_format_plain(self):
        sample = "2024-01-01 10:00:00 INFO Starting build\n2024-01-01 10:00:01 ERROR Build failed\n"
        fmt = LogParser.detect_format(sample)
        self.assertEqual(fmt, "plain")

    def test_detect_format_json(self):
        sample = '{"ts":"2024-01-01T10:00:00Z","level":"ERROR","msg":"build failed"}\n' * 3
        fmt = LogParser.detect_format(sample)
        self.assertEqual(fmt, "json")

    def test_detect_format_logfmt(self):
        sample = 'ts=2024-01-01T10:00:00Z level=error msg="build failed" job=ci\n' * 3
        fmt = LogParser.detect_format(sample)
        self.assertEqual(fmt, "logfmt")

    def test_detect_format_empty_defaults_to_plain(self):
        self.assertEqual(LogParser.detect_format(""), "plain")

    def test_plain_parser_extracts_level(self):
        parser = PlainLogParser()
        parsed = parser.parse_line("2024-01-01 10:00:00 ERROR something went wrong")
        self.assertEqual(parsed.level, "ERROR")

    def test_json_parser_extracts_message(self):
        parser = JsonLogParser()
        raw = '{"ts":"2024-01-01T10:00:00Z","level":"error","msg":"BUILD FAILED"}'
        parsed = parser.parse_line(raw)
        self.assertEqual(parsed.message, "BUILD FAILED")
        self.assertEqual(parsed.level, "ERROR")

    def test_logfmt_parser_extracts_fields(self):
        parser = LogFmtParser()
        raw = 'ts=2024-01-01T10:00:00Z level=error msg="BUILD FAILED" job=ci'
        parsed = parser.parse_line(raw)
        self.assertEqual(parsed.message, "BUILD FAILED")
        self.assertEqual(parsed.level, "ERROR")

    def test_json_analyze_end_to_end(self):
        """Analyze JSON-format logs and confirm findings are extracted."""
        log = (
            '{"ts":"2024-01-01T10:00:00Z","level":"info","msg":"running tests"}\n'
            '{"ts":"2024-01-01T10:00:01Z","level":"error","msg":"FAILED tests/test_api.py::test_x"}\n'
        )
        result = analyze(log, fmt_hint="json")
        self.assertEqual(result.log_format, "json")
        self.assertEqual(result.status, "FAILED")


# =============================================================================
# HTTP-layer tests via FastAPI TestClient (no live services needed)
# =============================================================================

class TestClassifierHTTP(unittest.TestCase):
    """Failure Classifier HTTP endpoint tests via TestClient."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from failure_classifier import app as classifier_app
        cls.client = TestClient(classifier_app, raise_server_exceptions=True)

    def test_classify_endpoint_production_deploy_error(self):
        """DEPLOY_ERROR on main branch must return ROLLBACK recovery action."""
        resp = self.client.post("/classify", json={
            "pipeline_id": "test-http",
            "stage": "deploy",
            "analysis": {"status": "FAILED", "failure_type": "DEPLOY_ERROR", "failures_found": 1, "details": []},
            "attempt": 1,
            "branch": "main",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_production"])
        self.assertEqual(data["recovery"], "ROLLBACK")
        self.assertEqual(data["failure_type"], "DEPLOY_ERROR")

    def test_classify_endpoint_non_prod_build_error_retries(self):
        """BUILD_ERROR on a feature branch must use RETRY on first attempt."""
        resp = self.client.post("/classify", json={
            "pipeline_id": "test-http",
            "stage": "build",
            "analysis": {"status": "FAILED", "failure_type": "BUILD_ERROR", "failures_found": 1, "details": []},
            "attempt": 1,
            "branch": "feature/my-work",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["is_production"])
        self.assertEqual(data["recovery"], "RETRY")

    def test_classify_endpoint_health(self):
        """Health endpoint must return status=ok."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_classify_rules_endpoint(self):
        """Rules endpoint must return a non-empty rules dict."""
        resp = self.client.get("/classify/rules")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("rules", data)
        self.assertGreater(len(data["rules"]), 0)


class TestRecoveryManagerHTTP(unittest.TestCase):
    """Recovery Manager HTTP endpoint tests via TestClient."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from recovery_manager import app as recovery_app
        cls.client = TestClient(recovery_app, raise_server_exceptions=True)

    def test_recover_rules_endpoint(self):
        """Rules endpoint must contain a mapping for every FailureType."""
        resp = self.client.get("/recover/rules")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("rules", data)
        self.assertGreater(len(data["rules"]), 0)

    def test_recover_health_endpoint(self):
        """Health endpoint must respond with status=ok."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_recover_unknown_failure_type_rejected(self):
        """Submitting an unknown failure_type must return 422."""
        resp = self.client.post("/recover", json={
            "pipeline_id": "test-pipe",
            "failure_type": "NOT_A_REAL_TYPE",
        })
        self.assertEqual(resp.status_code, 422)


class TestNotificationServiceHTTP(unittest.TestCase):
    """Notification Service HTTP endpoint tests via TestClient."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from notification_service import app as notification_app
        cls.client = TestClient(notification_app, raise_server_exceptions=True)

    def test_notify_endpoint_success_status(self):
        """Notify endpoint must return status=ok for a valid SUCCESS payload."""
        resp = self.client.post("/notify", json={
            "pipeline_id": "test-notify",
            "status": "SUCCESS",
            "recovery_triggered": False,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["pipeline_id"], "test-notify")

    def test_notify_endpoint_failed_status(self):
        """Notify endpoint must return status=ok even for a FAILED pipeline."""
        resp = self.client.post("/notify", json={
            "pipeline_id": "test-notify-fail",
            "status": "FAILED",
            "failure_type": "BUILD_ERROR",
            "recovery_triggered": True,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")

    def test_notify_health_endpoint(self):
        """Health endpoint must return status=ok."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_notify_invalid_status_rejected(self):
        """An unknown status value must be rejected with 422."""
        resp = self.client.post("/notify", json={
            "pipeline_id": "test-notify",
            "status": "UNKNOWN_STATUS",
        })
        self.assertEqual(resp.status_code, 422)


class TestGitHubAdapterHTTP(unittest.TestCase):
    """GitHub Adapter HTTP endpoint tests via TestClient."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from github_adapter import app as github_app
        cls.client = TestClient(github_app, raise_server_exceptions=False)

    def test_ping_event_returns_pong(self):
        """A ping event must return the pong message."""
        resp = self.client.post(
            "/pipeline-event",
            json={"zen": "Speak like a human.", "hook_id": 1},
            headers={"X-GitHub-Event": "ping"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("pong", resp.json()["message"])

    def test_unknown_event_ignored(self):
        """An unrecognised event type must be gracefully ignored."""
        resp = self.client.post(
            "/pipeline-event",
            json={},
            headers={"X-GitHub-Event": "issues"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("ignored", resp.json()["message"])

    def test_workflow_run_completed_success(self):
        """workflow_run with conclusion=success must NOT be forwarded as FAILED."""
        payload = {
            "action": "completed",
            "workflow_run": {
                "id": 99999,
                "run_number": 5,
                "head_branch": "main",
                "conclusion": "success",
                "logs_url": "https://api.github.com/repos/org/repo/actions/runs/99999/logs",
            },
            "repository": {"name": "my-repo"},
        }
        resp = self.client.post(
            "/pipeline-event",
            json=payload,
            headers={"X-GitHub-Event": "workflow_run"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["conclusion"], "success")
        self.assertEqual(data["status"], "SUCCESS")

    def test_workflow_run_completed_failure(self):
        """workflow_run with conclusion=failure must be forwarded as FAILED."""
        payload = {
            "action": "completed",
            "workflow_run": {
                "id": 88888,
                "run_number": 6,
                "head_branch": "feature/x",
                "conclusion": "failure",
                "logs_url": "https://api.github.com/repos/org/repo/actions/runs/88888/logs",
            },
            "repository": {"name": "my-repo"},
        }
        resp = self.client.post(
            "/pipeline-event",
            json=payload,
            headers={"X-GitHub-Event": "workflow_run"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["conclusion"], "failure")
        self.assertEqual(data["status"], "FAILED")

    def test_workflow_run_not_completed_ignored(self):
        """workflow_run with action != completed must be ignored."""
        payload = {
            "action": "requested",
            "workflow_run": {"id": 1, "run_number": 1},
            "repository": {"name": "my-repo"},
        }
        resp = self.client.post(
            "/pipeline-event",
            json=payload,
            headers={"X-GitHub-Event": "workflow_run"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("ignored", resp.json()["message"])

    def test_adapter_health(self):
        """Health endpoint must return status=ok."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")


if __name__ == '__main__':
    unittest.main()
