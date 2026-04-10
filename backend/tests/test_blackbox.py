import unittest
import urllib.request
import json
import urllib.error

class TestAllServicesBlackBox(unittest.TestCase):
    
    # ── 1. Failure Classifier (Port 8000 - Black Box API Test) ──
    def test_fc_classify_endpoint(self):
        print("\n[INFO] Starting Black Box Test: Failure Classifier (Port 8000)")
        # We send an opaque payload and only assess the generated JSON Response output structure
        url = "http://localhost:8000/classify"
        payload = json.dumps({
            "pipeline_id": "test-box",
            "stage": "build",
            "analysis": {"status": "FAILED", "failure_type": "DEPLOY_ERROR", "failures_found": 1, "details": []},
            "attempt": 1,
            "branch": "main"  # 'main' triggers Production flags
        }).encode('utf-8')
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        
        print(f"[INFO] Sending POST {url} with mock DEPLOY_ERROR payload on 'main' branch...")
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode())
            print(f"[INFO] Success! Received HTTP 200 OK. Response data: {data}")
            
            # Since this is a DEPLOY_ERROR on production ("main"), the rule engine should enforce a ROLLBACK!
            self.assertTrue(data["is_production"])
            self.assertEqual(data["recovery"], "ROLLBACK", "API failed to trigger production rollback constraint")
            print("[INFO] Verified: System securely triggered a ROLLBACK for production deployment error.")

    # ── 2. Recovery Manager (Port 8001 - Black Box API Test) ──
    def test_rm_recover_endpoint(self):
        print("\n[INFO] Starting Black Box Test: Recovery Manager (Port 8001)")
        # Even if Jenkins is not configured, API should respond safely with attempts evaluated
        url = "http://localhost:8001/recover"
        payload = json.dumps({
            "pipeline_id": "test-box",
            "failure_type": "TEST_FAILURE",
            "attempt": 1
        }).encode('utf-8')
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        
        print(f"[INFO] Sending POST {url} requesting automatic recovery for generic TEST_FAILURE...")
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode())
            print(f"[INFO] Success! Received HTTP 200 OK. Response data: {data}")
            
            self.assertEqual(data["action_taken"], "RETRY")
            self.assertIn("message", data)
            print("[INFO] Verified: System correctly assigned RETRY strategy.")

    # ── 3. Notification Service (Port 7000 - Black Box API Test) ──
    def test_ns_notify_endpoint(self):
        print("\n[INFO] Starting Black Box Test: Notification Service (Port 7000)")
        # Submit valid HTTP requests and verify standard network communication behavior
        url = "http://localhost:7000/notify"
        payload = json.dumps({
            "pipeline_id": "test-notify-id",
            "status": "SUCCESS",
            "recovery_triggered": False
        }).encode('utf-8')
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        
        print(f"[INFO] Sending POST {url} to dispatch notification for successful pipeline...")
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode())
            print(f"[INFO] Success! Received HTTP 200 OK. Response data: {data}")
            
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["pipeline_id"], "test-notify-id")
            print("[INFO] Verified: Notification dispatched accurately without crashing.")

    # ── 4. Pipeline Controller (Port 9000 - Black Box Boundary Test) ──
    def test_pc_pipeline_event_endpoint_boundary(self):
        print("\n[INFO] Starting Black Box Test: Pipeline Controller Boundary Security (Port 9000)")
        # Boundary Edge-Case API testing: Passing wildly invalid string types to test framework protections
        url = "http://localhost:9000/pipeline-event"
        payload = json.dumps({
            "event_id": "1",    # Fails min_length
            "pipeline_id": "t", # Fails min_length
            "run_number": 0,    # Fails gt0
        }).encode('utf-8')
        
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        print(f"[INFO] Intentionally sending MALFORMED POST to {url} to test Validation framework vulnerabilities...")
        
        try:
            urllib.request.urlopen(req)
            self.fail("API must strictly protect endpoints returning 422 Unprocessable Entity error codes.")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 422) 
            print(f"[INFO] Pass! API successfully blocked the bad request and threw HTTP {e.code} Unprocessable Entity.")

if __name__ == '__main__':
    unittest.main()
