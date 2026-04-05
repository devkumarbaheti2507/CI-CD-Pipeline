from datetime import datetime
from pipeline_status import PipelineStatus

class PipelineMonitor:
    def __init__(self):
        self.monitored_pipelines = []
        print("Pipeline Monitor initialized")

    def add_pipeline(self, pipeline):
        self.monitored_pipelines.append(pipeline)
        print(f"Now monitoring: {pipeline.pipeline_name}")

    def check_for_failures(self):
        failed_pipelines = []
        print("\n--- Checking all pipelines for failures ---")

        for pipeline in self.monitored_pipelines:
            if pipeline.status == PipelineStatus.FAILED:
                print(f" FAILURE DETECTED in '{pipeline.pipeline_name}'")
                print(f"  Error: {pipeline.error_message}")
                failed_pipelines.append(pipeline)
            elif pipeline.status == PipelineStatus.RUNNING:
                print(f" '{pipeline.pipeline_name}' is still running...")
            elif pipeline.status == PipelineStatus.SUCCESS:
                print(f" '{pipeline.pipeline_name}' is healthy")

        return failed_pipelines

    def get_failure_report(self, pipeline):
        if pipeline.status != PipelineStatus.FAILED:
            return None

        return {
            "pipeline_name": pipeline.pipeline_name,
            "branch": pipeline.branch_name,
            "error": pipeline.error_message,
            "failed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
