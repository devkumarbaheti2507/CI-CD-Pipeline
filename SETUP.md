# Local Setup Guide

Step-by-step instructions to get the CI/CD Pipeline project running on your machine after cloning the repository.

---

## Prerequisites

Install the following tools before you begin:

| Tool | Version | Purpose |
|---|---|---|
| [Git](https://git-scm.com/) | any | clone the repository |
| [Python](https://www.python.org/downloads/) | 3.10 or newer | run backend services |
| [Node.js & npm](https://nodejs.org/) | 18 LTS or newer | run the React dashboard |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | any | run Redis and Jenkins |
| [ngrok](https://ngrok.com/download) | any | expose the GitHub Webhook Adapter to the internet |

---

## 1. Clone the repository

```bash
git clone https://github.com/devkumarbaheti2507/CI-CD-Pipeline.git
cd CI-CD-Pipeline
```

---

## 2. Set up the backend

### 2a. Create a Python virtual environment (recommended)

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 2b. Install Python dependencies

```bash
cd backend
pip install -r requirements.txt
cd ..
```

### 2c. Create the backend `.env` file

```bash
# Windows
copy backend\.env.example backend\.env

# macOS / Linux
cp backend/.env.example backend/.env
```

Open `backend/.env` and fill in the required values:

| Variable | What to put |
|---|---|
| `JENKINS_TOKEN` | Your Jenkins API token (created in Jenkins → User → Configure → API Token) |
| `STATUS_API_KEY` | Any random secret string you choose |
| `GITHUB_WEBHOOK_SECRET` | A secret you define and later set on your GitHub webhook |
| `EMAIL_USER` / `EMAIL_PASS` / `EMAIL_TO` | Only needed if you set `EMAIL_ENABLED=true` |
| `SLACK_WEBHOOK_URL` | Only needed if you set `SLACK_ENABLED=true` |

All other values can be left at their defaults for local development.

---

## 3. Set up the frontend

### 3a. Install Node dependencies

```bash
cd frontend
npm install
cd ..
```

### 3b. Create the frontend `.env` file (optional)

The default service URLs work without any changes for local development. If you changed any backend ports, copy and edit the file:

```bash
# Windows
copy frontend\.env.example frontend\.env

# macOS / Linux
cp frontend/.env.example frontend/.env
```

---

## 4. Make sure Docker Desktop is running

Open Docker Desktop and wait until it shows **"Docker Desktop is running"** in the system tray before proceeding.

---

## 5. Start all backend services

From the **project root**, run the start script:

```bat
scripts\start.bat
```

This script will:

1. Start a **Redis** container on port `6379` (creates one automatically if it doesn't exist).
2. Start a **Jenkins** container on port `8080` (first startup can take ~60 seconds).
3. Open six separate terminal windows, one for each backend microservice:

| Service | Port |
|---|---|
| Log Analyzer | 5001 |
| Failure Classifier | 8000 |
| Recovery Manager | 8001 |
| Notification Service | 7000 |
| Pipeline Controller | 9000 |
| GitHub Adapter | 9001 |

Wait until all six windows show a **Uvicorn running on …** line before continuing.

---

## 6. Start the React dashboard

Open a **new terminal** at the project root and run:

```bash
cd frontend
npm start
```

The dashboard opens automatically at **http://localhost:3000**.

---

## 7. Expose the webhook adapter with ngrok (optional)

If you want GitHub to send real webhook events to your local machine, open another **new terminal** and run:

```bash
ngrok http 9001
```

Copy the `https://…ngrok-free.app` URL that ngrok prints and add it as a webhook in your GitHub repository:

- **Payload URL:** `https://<your-ngrok-url>/webhook`
- **Content type:** `application/json`
- **Secret:** the value you set for `GITHUB_WEBHOOK_SECRET` in `backend/.env`
- **Events:** choose *Just the push event* or whichever events you need

---

## 8. Verify everything is working

Open a browser and check each health endpoint:

| Service | Health URL |
|---|---|
| Log Analyzer | http://localhost:5001/api/v1/health |
| Failure Classifier | http://localhost:8000/health |
| Recovery Manager | http://localhost:8001/health |
| Notification Service | http://localhost:7000/health |
| Pipeline Controller | http://localhost:9000/health |
| GitHub Adapter | http://localhost:9001/health |
| Jenkins | http://localhost:8080 |
| Dashboard | http://localhost:3000 |

Each health endpoint should return a `200 OK` response.

---

## 9. Stop all services

From the **project root**, run:

```bat
scripts\stop.bat
```

This stops all backend service windows and the Docker containers.

---

## Running Tests

### White-box (unit) tests — no running services required

```bash
cd backend
python -m pytest tests/test_whitebox.py -v
```

### Black-box (integration) tests — all services must be running first

```bash
cd backend
python -m pytest tests/test_blackbox.py -v
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `docker: command not found` | Install Docker Desktop and make sure it is running |
| A service window closes immediately | Check the terminal output for import errors; run `pip install -r requirements.txt` inside the virtual environment |
| Port already in use | Stop any other process using that port, or change the port in both the script and `backend/.env` |
| Jenkins takes too long to start | Wait the full 60 seconds; on first run Jenkins unpacks its WAR file |
| ngrok session expired | Free ngrok sessions expire after a few hours; simply restart `ngrok http 9001` and update the webhook URL on GitHub |
