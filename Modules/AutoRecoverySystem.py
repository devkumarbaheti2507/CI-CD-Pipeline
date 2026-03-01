class AutoRecoverySystem:
    def __init__(self):
        self.strategies = []
        print("Auto Recovery System initialized")

    def add_strategy(self, strategy):
        self.strategies.append(strategy)
        print(f"Added strategy: {strategy.strategy_name}")

    def attempt_recovery(self, pipeline):
        print("\n" + "=" * 50)
        print("ATTEMPTING AUTOMATIC RECOVERY")
        print("=" * 50)
        print(f"Pipeline: {pipeline.pipeline_name}")
        print(f"Error: {pipeline.error_message}")

        if not self.strategies:
            print("\n⚠ No recovery strategies available!")
            return False

        for i, strategy in enumerate(self.strategies, 1):
            print(f"\nStrategy {i}/{len(self.strategies)}: {strategy.strategy_name}")
            success = strategy.recover(pipeline)
            if success:
                print(f"\n✓ Recovery successful using {strategy.strategy_name}")
                return True

        print("\n✗ All recovery strategies failed")
        return False
