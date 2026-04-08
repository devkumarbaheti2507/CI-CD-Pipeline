@echo off
title CI/CD Pipeline - Stopping All Services
color 0C
cls

echo.
echo  ============================================
echo    CI/CD Pipeline - Stopping All Services
echo  ============================================
echo.

echo [*] Stopping Python services (uvicorn + log_analyzer)...
taskkill /F /FI "WINDOWTITLE eq Log Analyzer :5001*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Failure Classifier :8000*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Recovery Manager :6001*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Notification Service :7000*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Pipeline Controller :9000*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq GitHub Adapter :9001*" >nul 2>&1
echo [OK] Python service windows closed

echo [*] Killing all remaining Python processes...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM python3.exe /T >nul 2>&1
echo [OK] Python processes stopped

echo [*] Stopping ngrok...
taskkill /F /IM ngrok.exe /T >nul 2>&1
echo [OK] ngrok stopped

echo [*] Stopping Redis container...
docker stop redis >nul 2>&1
echo [OK] Redis stopped

echo [*] Stopping Jenkins container...
docker stop jenkins >nul 2>&1
echo [OK] Jenkins stopped

echo.
echo  ============================================
echo    All services stopped successfully!
echo.
echo    To start again double-click start_all.bat
echo  ============================================
echo.
pause
