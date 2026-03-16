# CI/CD Pipeline Dashboard

React UI for the CS 331 CI/CD Pipeline with Automated Failure Recovery project.

## Quick Start

```bash
# 1. Install dependencies
npm install

# 2. Start development server (port 3000)
npm start

# 3. Build for production
npm run build
```

## Pages

| Page | Purpose |
|------|---------|
| Dashboard | Live service health + pipeline event history |
| Trigger Pipeline | Fire a pipeline event, watch job status |
| Log Analyzer | Paste build logs → analyze → classify |
| Failure Classifier | Classify failures directly |
| Recovery Manager | Trigger recovery actions |
| Notifications | Send alerts, view history |
| Settings | Service URLs, CORS setup guide |

## Configuration

Copy `.env.example` to `.env` and set service URLs if needed.

## CORS

See `CORS_SETUP.md` — you must add CORS middleware to all Python services.
