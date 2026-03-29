@echo off
title CI/CD Pipeline - Startup
color 0A
cls

echo.
echo  ============================================
echo    CI/CD Pipeline - Automated Recovery
echo    Starting all services...
echo  ============================================
echo.

:: ── Configuration — Edit these values ────────────────────────
set REDIS_URL=redis://localhost:6379
set STATUS_API_KEY=mysecretkey123
set ALLOWED_LOG_HOSTS=localhost,127.0.0.1
set JENKINS_URL=http://localhost:8080
set JENKINS_USER=admin
set JENKINS_TOKEN=1169165d0fe8694a8116e084b26901a58a
set LOG_ANALYZER_URL=http://localhost:5001/api/v1/analyze
set LOG_ANALYZER_HEALTH_URL=http://localhost:5001/api/v1/health
set RECOVERY_SERVICE_URL=http://localhost:6001/recover
set RECOVERY_HEALTH_URL=http://localhost:6001/health
set NOTIFICATION_SERVICE_URL=http://localhost:7000/notify
set NOTIFICATION_HEALTH_URL=http://localhost:7000/health
set PIPELINE_CONTROLLER_URL=http://localhost:9000/pipeline-event
set GITHUB_WEBHOOK_SECRET=
:: ─────────────────────────────────────────────────────────────

echo [*] Starting Redis...
docker start redis >nul 2>&1
if errorlevel 1 (
    echo [*] Creating new Redis container...
    docker run -d -p 6379:6379 --name redis redis:7 >nul 2>&1
)
echo [OK] Redis on port 6379
timeout /t 2 /nobreak >nul

echo [*] Starting Jenkins...
docker start jenkins >nul 2>&1
if errorlevel 1 (
    echo [*] Creating new Jenkins container...
    docker run -d -p 8080:8080 -p 50000:50000 -v jenkins_home:/var/jenkins_home --name jenkins jenkins/jenkins:lts >nul 2>&1
    echo [OK] Jenkins created — wait 60 seconds for first startup
    timeout /t 60 /nobreak >nul
) else (
    echo [OK] Jenkins on port 8080
)
timeout /t 3 /nobreak >nul

echo.
echo [1/6] Starting Log Analyzer on port 5001...
start "Log Analyzer :5001" cmd /k "cd /d %~dp0 && python log_analyzer.py"
timeout /t 3 /nobreak >nul

echo [2/6] Starting Failure Classifier on port 8000...
start "Failure Classifier :8000" cmd /k "cd /d %~dp0 && python -m uvicorn failure_classifier:app --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul

echo [3/6] Starting Recovery Manager on port 6001...
start "Recovery Manager :6001" cmd /k "cd /d %~dp0 && set JENKINS_URL=%JENKINS_URL%&& set JENKINS_USER=%JENKINS_USER%&& set JENKINS_TOKEN=%JENKINS_TOKEN%&& python -m uvicorn recovery_manager:app --host 0.0.0.0 --port 6001"
timeout /t 3 /nobreak >nul

echo [4/6] Starting Notification Service on port 7000...
start "Notification Service :7000" cmd /k "cd /d %~dp0 && python -m uvicorn notification_service:app --host 0.0.0.0 --port 7000"
timeout /t 3 /nobreak >nul

echo [5/6] Starting Pipeline Controller on port 9000...
start "Pipeline Controller :9000" cmd /k "cd /d %~dp0 && set REDIS_URL=%REDIS_URL%&& set STATUS_API_KEY=%STATUS_API_KEY%&& set ALLOWED_LOG_HOSTS=%ALLOWED_LOG_HOSTS%&& set JENKINS_USER=%JENKINS_USER%&& set JENKINS_TOKEN=%JENKINS_TOKEN%&& set LOG_ANALYZER_URL=%LOG_ANALYZER_URL%&& set LOG_ANALYZER_HEALTH_URL=%LOG_ANALYZER_HEALTH_URL%&& set RECOVERY_SERVICE_URL=%RECOVERY_SERVICE_URL%&& set RECOVERY_HEALTH_URL=%RECOVERY_HEALTH_URL%&& set NOTIFICATION_SERVICE_URL=%NOTIFICATION_SERVICE_URL%&& set NOTIFICATION_HEALTH_URL=%NOTIFICATION_HEALTH_URL%&& python -m uvicorn pipeline_controller:app --host 0.0.0.0 --port 9000"
timeout /t 4 /nobreak >nul

echo [6/6] Starting GitHub Webhook Adapter on port 9001...
start "GitHub Adapter :9001" cmd /k "cd /d %~dp0 && set PIPELINE_CONTROLLER_URL=%PIPELINE_CONTROLLER_URL%&& set JENKINS_URL=%JENKINS_URL%&& set GITHUB_WEBHOOK_SECRET=%GITHUB_WEBHOOK_SECRET%&& python -m uvicorn github_adapter:app --host 0.0.0.0 --port 9001"
timeout /t 3 /nobreak >nul

echo.
echo  ============================================
echo    All 6 services started!
echo.
echo    Ports:
echo    Pipeline Controller  :9000
echo    GitHub Adapter       :9001
echo    Log Analyzer         :5001
echo    Failure Classifier   :8000
echo    Recovery Manager     :6001
echo    Notification Service :7000
echo    Redis                :6379
echo    Jenkins              :8080
echo.
echo    Dashboard  : http://localhost:3000
echo    Jenkins    : http://localhost:8080
echo.
echo    Now start ngrok in a new window:
echo    ngrok http 9001
echo.
echo    Then start the UI in a new window:
echo    cd cicd-dashboard ^& npm start
echo  ============================================
echo.
pause
