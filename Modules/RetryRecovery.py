import time
import random
from recovery_strategy import RecoveryStrategy

class RetryRecovery(RecoveryStrategy):
    def __init__(self, max_retries=3):
        super().__init__("Retry Recovery")
        self.max_retries = max_retries

    def recover(self, pipeline):
        print(f"\n--- Starting {self.strategy_name} ---")
        print(f"Will attempt up to {self.max_retries} retries")

        for attempt in range(1, self.max_retries + 1):
            print(f"\nRetry attempt {attempt}/{self.max_retries}...")
            time.sleep(1)
            success = random.choice([True, False])

            if success:
                print(f"✓ Retry successful on attempt {attempt}!")
                pipeline.mark_success()
                return True
            else:
                print(f"✗ Attempt {attempt} failed")

        print(f"\n✗ All {self.max_retries} retry attempts exhausted")
        return False
