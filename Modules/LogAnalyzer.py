class LogAnalyzer:
    def __init__(self, logs):
        self.logs = logs

    def detect_failure(self):
        for log in self.logs:
            if "ERROR" in log or "FAIL" in log:
                return True
        return False

    def analyze_logs(self):
        for log in self.logs:
            if "BUILD_FAIL" in log:
                return "BUILD_FAILURE"
            elif "TEST_FAIL" in log:
                return "TEST_FAILURE"
            elif "DEPLOY_FAIL" in log:
                return "DEPLOYMENT_FAILURE"
        return "UNKNOWN_FAILURE"