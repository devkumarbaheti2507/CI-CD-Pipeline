# Backend — CI/CD Pipeline

Python microservices that power the CI/CD Pipeline automated-recovery system.

## Services

| File | Port | Description |
|---|---|---|
| `pipeline_controller.py` | 9000 | Accepts pipeline events, orchestrates recovery |
| `log_analyzer.py` | 5001 | Parses and classifies raw build/test logs |
| `failure_classifier.py` | 8000 | Maps failure type + branch to severity and recovery action |
| `recovery_manager.py` | 6001 | Executes recovery actions (retry, rollback, restart via Jenkins) |
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

---

## Vercel Deployment

The backend ships a single FastAPI monolith entry-point (`main.py`) that mounts all six microservices at sub-paths, making it deployable as a Vercel serverless function.

**Deploy steps:**

1. Import the repository into [vercel.com](https://vercel.com).
2. Set the **Root Directory** to the repository root (not `backend/`).
3. Vercel will detect `vercel.json` at the root and use `backend/main.py` as the Python entry-point.
4. Add your environment variables in the Vercel project settings (see `.env.example`).
5. After deployment, copy the Vercel URL and paste it into `frontend/.env.production` for the frontend build.

**Sub-path routing (from `vercel.json`):**

| Path prefix | Mounted service |
|---|---|
| `/classifier/*` | Failure Classifier |
| `/github/*` | GitHub Adapter |
| `/notification/*` | Notification Service |
| `/pipeline/*` | Pipeline Controller |
| `/recovery/*` | Recovery Manager |
| `/api/v1/*` | Log Analyzer |
| `/*` | Root health check |

> **Note:** Redis and Jenkins are external dependencies. Vercel serverless functions are stateless — you will need a managed Redis (e.g. Upstash) and an externally hosted Jenkins instance for full functionality on Vercel.
