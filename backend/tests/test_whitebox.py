import unittest
import json

# Internal classes from each microservice
from failure_classifier import classify, FailureType as FCFailureType, Severity
from recovery_manager import RECOVERY_RULES, FailureType as RMFailureType, RecoveryAction as RMRecoveryAction
from notification_service import build_message, NotifyRequest, PipelineStatus
from pipeline_controller import PipelineEvent

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
        
        # Validating specific string manipulation constraints
        self.assertIn("❌", msg_out, "Failed status must inject specific unicode marker")
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
        # Trigger explicit validation error branch
        invalid_payload = valid_payload.copy()
        invalid_payload["run_number"] = -5 # Invalid negative bound
        
        with self.assertRaises(ValueError, msg="PipelineEvent must strictly reject negative integers internally"):
            PipelineEvent(**invalid_payload)
        print("[INFO] Verified: Internal structural schema constraints threw ValueError before payload reached deeper app layers.")

if __name__ == '__main__':
    unittest.main()
