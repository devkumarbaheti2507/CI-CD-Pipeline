class RecoveryStrategy:
    def __init__(self, strategy_name):
        self.strategy_name = strategy_name

    def recover(self, pipeline):
        raise NotImplementedError
