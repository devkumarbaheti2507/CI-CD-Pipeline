import time
from datetime import datetime
from recovery_strategy import RecoveryStrategy

class NotifyRecovery(RecoveryStrategy):
    def __init__(self):
        super().__init__("Notify Recovery")

    def recover(self, pipeline):
        print(f"\n--- Starting {self.strategy_name} ---")
        notification = self._create_notification(pipeline)
        print("\n Sending notification to development team...")
        time.sleep(1)
        print("✓ Notification sent successfully!")
        print("\nNotification contents:")
        print(notification)
        return True

    def _create_notification(self, pipeline):
        return f"""Subject: Pipeline Failure Alert

Pipeline: {pipeline.pipeline_name}
Branch: {pipeline.branch_name}
Status: FAILED
Error: {pipeline.error_message}
Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Action Required: Please investigate and fix the issue."""
