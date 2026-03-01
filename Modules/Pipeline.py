from datetime import datetime
from pipeline_status import PipelineStatus

class Pipeline:
    def __init__(self, pipeline_name, branch_name):
        self.pipeline_name = pipeline_name
        self.branch_name = branch_name
        self.status = PipelineStatus.PENDING
        self.error_message = ""
        self.start_time = None

    def start(self):
        self.status = PipelineStatus.RUNNING
        self.start_time = datetime.now()
        print(f"✓ Pipeline '{self.pipeline_name}' started on branch '{self.branch_name}'")

    def mark_success(self):
        self.status = PipelineStatus.SUCCESS
        print(f"✓ Pipeline '{self.pipeline_name}' completed successfully!")

    def mark_failed(self, error_message):
        self.status = PipelineStatus.FAILED
        self.error_message = error_message
        print(f"✗ Pipeline '{self.pipeline_name}' FAILED: {error_message}")
