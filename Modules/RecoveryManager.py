class RecoveryManager:
    def execute_recovery(self, failure_type):
        if failure_type == "BUILD_FAILURE":
            print("Retrying build...")
        elif failure_type == "TEST_FAILURE":
            print("Re-running tests...")
        elif failure_type == "DEPLOYMENT_FAILURE":
            self.rollback_deployment()
        else:
            print("Manual intervention required")

    def rollback_deployment(self):
        print("Rolling back to last stable deployment...")