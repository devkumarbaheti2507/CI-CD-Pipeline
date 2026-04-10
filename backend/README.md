# Backend — CI/CD Pipeline

Python microservices that power the CI/CD Pipeline automated-recovery system.

## Services

| File | Port | Description |
|---|---|---|
| `pipeline_controller.py` | 9000 | Accepts pipeline events, orchestrates recovery |
| `log_analyzer.py` | 5001 | Parses and classifies raw build/test logs |
| `failure_classifier.py` | 8000 | Maps failure type + branch to severity and recovery action |
| `recovery_manager.py` | 8001 | Executes recovery actions (retry, rollback, restart via Jenkins) |
| `notification_service.py` | 7000 | Sends email / Slack / webhook alerts |
| `github_adapter.py` | 9001 | Validates GitHub webhook signatures and forwards events |
| `main.py` | — | FastAPI monolith entry-point for serverless deployment (Vercel) |

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

## Running locally

Use the provided scripts from the project root:

```
scripts\start.bat   # starts all 6 services + Redis + Jenkins
scripts\stop.bat    # stops everything
```

## Tests

```bash
# White-box (unit) tests — no running services needed
pytest tests/test_whitebox.py -v

# Black-box (integration) tests — all services must be running
pytest tests/test_blackbox.py -v
``` 
