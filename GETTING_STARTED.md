# Getting Started — CI/CD Pipeline Controller

This guide walks you through every step needed to get the project running on your own machine after cloning the repository.

---

## Prerequisites

Install the following tools before you start. The version numbers are the minimum tested versions.

| Tool | Minimum Version | Download |
|---|---|---|
| **Git** | any | https://git-scm.com |
| **Python** | 3.11 | https://www.python.org/downloads/ |
| **Node.js** | 18 (20 recommended) | https://nodejs.org |
| **Docker Desktop** | 24 | https://www.docker.com/products/docker-desktop/ |
| **Docker Compose** | v2 (bundled with Docker Desktop) | — |

> **Note:** Docker is required for Redis and Jenkins in both the Docker-based and manual startup paths. If you only want to run the Python services without Jenkins, you still need Docker for Redis (or install Redis natively).

---

## Step 1 — Clone the Repository

```bash
git clone https://github.com/devkumarbaheti2507/CI-CD-Pipeline.git
cd CI-CD-Pipeline
```

---

## Step 2 — Configure Environment Variables

The backend services read their configuration from a `.env` file.

```bash
# Windows (Command Prompt)
copy backend\.env.example backend\.env

# macOS / Linux
cp backend/.env.example backend/.env
```

Open `backend/.env` in any text editor and review the values. For a basic local run the defaults work out of the box — the only fields you may want to change are:

| Field | What to put |
|---|---|
| `JENKINS_TOKEN` | Your Jenkins API token (leave blank to skip Jenkins integration) |
| `STATUS_API_KEY` | Any random string you choose (e.g. `mysecretkey`) |
| `EMAIL_USER` / `EMAIL_PASS` / `EMAIL_TO` | Your Gmail credentials — only needed if `EMAIL_ENABLED=true` |
| `SLACK_WEBHOOK_URL` | Your Slack incoming webhook URL — only needed if `SLACK_ENABLED=true` |

---

## Option A — Start with Docker Compose (Recommended)

This single command starts **all** services (6 backend microservices, Redis, Jenkins, and the React frontend) in the correct order.

```bash
docker compose up --build
```

Wait for all containers to become healthy (usually 1–2 minutes on the first run while images are pulled and built). You will see log output from every service.

**Ports after startup:**

| URL | What it is |
|---|---|
| http://localhost:3000 | React dashboard (main UI) |
| http://localhost:9000 | Pipeline Controller API |
| http://localhost:5001/api/v1/health | Log Analyzer health check |
| http://localhost:8000/health | Failure Classifier health check |
| http://localhost:6001/health | Recovery Manager health check |
| http://localhost:7000/health | Notification Service health check |
| http://localhost:9001/health | GitHub Adapter health check |
| http://localhost:8080 | Jenkins |

To stop everything:

```bash
docker compose down
```

---

## Option B — Start Manually (No Docker for Python Services)

Use this path if you prefer to run the Python services directly. Docker is still used for Redis and Jenkins.

### Step B-1 — Install Python Dependencies

```bash
cd backend
pip install -r requirements.txt
```

> **Tip (Windows):** If `pip` is not on your PATH, use `python -m pip install -r requirements.txt`.

### Step B-2 — Start Redis and Jenkins via Docker

```bash
# Redis (required — must be running before the Pipeline Controller)
docker run -d -p 6379:6379 --name redis redis:7-alpine

# Jenkins (optional — only needed for recovery actions)
docker run -d -p 8080:8080 -p 50000:50000 \
  -v jenkins_home:/var/jenkins_home \
  --name jenkins jenkins/jenkins:lts
```

If the containers already exist from a previous run, start them with:

```bash
docker start redis jenkins
```

### Step B-3 — Start the Backend Services

#### Windows — one-click script

Double-click `scripts\start.bat` (or run it from a terminal).  
It opens a separate terminal window for each of the 6 services.

#### macOS / Linux — run each service in its own terminal tab

Open **6 terminal tabs**, `cd` into `backend/` in each, and run one command per tab:

```bash
# Tab 1 — Log Analyzer (uses built-in HTTP server, not uvicorn)
python log_analyzer.py

# Tab 2 — Failure Classifier
uvicorn failure_classifier:app --port 8000

# Tab 3 — Recovery Manager
uvicorn recovery_manager:app --port 6001

# Tab 4 — Notification Service
uvicorn notification_service:app --port 7000

# Tab 5 — Pipeline Controller
uvicorn pipeline_controller:app --port 9000

# Tab 6 — GitHub Adapter
uvicorn github_adapter:app --port 9001
```

Or start them all in the background with a single command (macOS/Linux):

```bash
python log_analyzer.py &
uvicorn failure_classifier:app  --port 8000 &
uvicorn recovery_manager:app    --port 6001 &
uvicorn notification_service:app --port 7000 &
uvicorn pipeline_controller:app  --port 9000 &
uvicorn github_adapter:app       --port 9001 &
```

Wait a few seconds for all services to initialise before opening the dashboard.

### Step B-4 — Start the Frontend

Open a **new terminal** in the project root:

```bash
cd frontend
npm install       # only needed the first time
npm start
```

The dashboard opens automatically at **http://localhost:3000**.

---

## Step 3 — Verify Everything is Running

Open the dashboard at http://localhost:3000.  
The **Dashboard** page shows a live health status for each service.  
All six service cards should show **green / healthy**.

You can also check each service manually:

```bash
curl http://localhost:5001/api/v1/health   # Log Analyzer
curl http://localhost:8000/health          # Failure Classifier
curl http://localhost:6001/health          # Recovery Manager
curl http://localhost:7000/health          # Notification Service
curl http://localhost:9000/health          # Pipeline Controller
curl http://localhost:9001/health          # GitHub Adapter
```

Each should return `{"status": "ok", ...}`.

---

## Step 4 — Run the Tests

```bash
cd backend

# Unit tests — no running services needed
python -m pytest tests/test_whitebox.py -v

# Integration tests — all 6 services + Redis must be running first
python -m pytest tests/test_blackbox.py -v
```

---

## Troubleshooting

### "Port already in use"
Another process is using that port. Find and kill it:

```bash
# macOS / Linux
lsof -i :9000        # replace 9000 with the conflicting port
kill -9 <PID>

# Windows (PowerShell)
netstat -ano | findstr :9000
taskkill /PID <PID> /F
```

### Pipeline Controller fails to start — "Cannot connect to Redis"
Redis must be running first. Check it:

```bash
docker ps | grep redis
```

If it is not listed, start it:

```bash
docker start redis
# or, if it does not exist yet:
docker run -d -p 6379:6379 --name redis redis:7-alpine
```

### Frontend shows "Network Error" / blank data
The frontend proxies API calls to `http://localhost:9000`. Make sure the Pipeline Controller is running on port 9000 before opening the dashboard.

### `pip install` fails — "Microsoft Visual C++ required" (Windows)
Install the [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) and retry.

### Docker Compose — service keeps restarting
Run `docker compose logs <service-name>` (e.g. `docker compose logs pipeline-controller`) to see the error output.

---

## Stopping Everything

**Docker Compose:**
```bash
docker compose down          # stop and remove containers (keeps data volumes)
docker compose down -v       # also remove volumes (wipes Jenkins data)
```

**Manual startup (macOS/Linux):**
```bash
# Kill all background uvicorn / python processes started in this shell
kill $(jobs -p)
```

**Manual startup (Windows):**
Close each of the 6 service terminal windows, or run `scripts\stop.bat`.
