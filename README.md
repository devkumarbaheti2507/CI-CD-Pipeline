# CI/CD Pipeline Controller

A group project for CS 331 (Software Engineering Lab) — an automated CI/CD Pipeline Controller with failure detection, classification, and recovery.

![Backend CI](https://github.com/devkumarbaheti2507/CI-CD-Pipeline/actions/workflows/backend-ci.yml/badge.svg)
![Frontend CI](https://github.com/devkumarbaheti2507/CI-CD-Pipeline/actions/workflows/frontend-ci.yml/badge.svg)
![Pipeline](https://github.com/devkumarbaheti2507/CI-CD-Pipeline/actions/workflows/pipeline.yml/badge.svg)

**Live Frontend:** https://ci-cd-pipeline-kappa.vercel.app/

---

## Architecture

```
GitHub Push / webhook
       |
       v
 GitHub Adapter (9001)          <- validates signature, maps conclusion -> status
       |
       v
Pipeline Controller (9000)      <- Redis-backed orchestrator + rate limiter + SSRF guard
       |
   +---+--------------------+
   v                        v
Log Analyzer (5001)   (if SUCCESS -> skip recovery)
   |
   v
Failure Classifier (8000)       <- maps failure type + branch -> severity + recovery action
   |
   +---> Recovery Manager (6001) <- retries, rollbacks, restarts via Jenkins
   |
   +---> Notification Service (7000) <- email / Slack / webhook alerts
```

| Service | Port | Description |
|---|---|---|
| Pipeline Controller | 9000 | Accepts events, orchestrates recovery |
| Log Analyzer | 5001 | Parses and classifies raw build logs |
| Failure Classifier | 8000 | Maps failure type + branch to severity and recovery action |
| Recovery Manager | 6001 | Executes recovery actions via Jenkins |
| Notification Service | 7000 | Sends email / Slack / webhook alerts |
| GitHub Adapter | 9001 | Validates GitHub webhook signatures and forwards events |

---

## Quick Start — Docker Compose

```bash
# 1. Clone and configure
git clone https://github.com/devkumarbaheti2507/CI-CD-Pipeline.git
cd CI-CD-Pipeline
cp backend/.env.example backend/.env   # fill in your credentials

# 2. Start everything (backend + Redis + Jenkins + frontend)
docker compose up --build

# 3. Open the dashboard
open http://localhost:3000
```

Services start in dependency order. Jenkins is available at http://localhost:8080.

---

## Quick Start — Local (without Docker)

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in your credentials
```

Start all services (Windows):
```
scripts\start.bat
```

Or start them individually:
```bash
LOG_ANALYZER_PORT=5001 python log_analyzer.py &
uvicorn failure_classifier:app   --port 8000 &
uvicorn recovery_manager:app     --port 6001 &
uvicorn notification_service:app --port 7000 &
uvicorn pipeline_controller:app  --port 9000 &
uvicorn github_adapter:app       --port 9001 &
```

### Frontend

```bash
cd frontend
npm install
npm start   # opens http://localhost:3000
```

---

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill in the values:

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `LOG_ANALYZER_URL` | `http://localhost:5001/api/v1/analyze` | Log Analyzer endpoint |
| `RECOVERY_SERVICE_URL` | `http://localhost:6001/recover` | Recovery Manager endpoint |
| `NOTIFICATION_SERVICE_URL` | `http://localhost:7000/notify` | Notification Service endpoint |
| `JENKINS_URL` | `http://localhost:8080` | Jenkins server URL |
| `JENKINS_USER` | `admin` | Jenkins user |
| `JENKINS_TOKEN` | *(empty)* | Jenkins API token |
| `STATUS_API_KEY` | *(empty)* | API key for `/pipeline-status` endpoint |
| `ALLOWED_LOG_HOSTS` | *(empty)* | Comma-separated hostnames exempt from SSRF check |
| `EMAIL_ENABLED` | `false` | Enable email notifications |
| `SLACK_ENABLED` | `false` | Enable Slack notifications |
| `GITHUB_WEBHOOK_SECRET` | *(empty)* | GitHub webhook secret for signature validation |

---

## Testing

```bash
cd backend

# White-box (unit) tests — no running services needed
pytest tests/test_whitebox.py -v

# Black-box (integration) tests — all services must be running
pytest tests/test_blackbox.py -v
```

Tests are automatically run by GitHub Actions on every push and pull request.

---

## Deployment

### Vercel (Backend)

The backend is deployable as a serverless monolith via Vercel using `backend/main.py` as the entry-point. All microservices are mounted as sub-paths.

See `vercel.json` at the repository root for the routing configuration.

### Vercel (Frontend)

The frontend is deployed automatically by Vercel from the `frontend/` directory.

For production, set the backend URL in `frontend/.env.production` (see the template) and trigger a new build.

---

## Project Requirements

See [docs/project-requirements.md](docs/project-requirements.md).
