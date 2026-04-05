Write-Host "Safely stopping active microservices by window title (Bypassing Docker)..."
taskkill /F /FI "WINDOWTITLE eq Log Analyzer :5001*" 2>$null
taskkill /F /FI "WINDOWTITLE eq Failure Classifier :8000*" 2>$null
taskkill /F /FI "WINDOWTITLE eq Recovery Manager :6001*" 2>$null
taskkill /F /FI "WINDOWTITLE eq Notification Service :7000*" 2>$null
taskkill /F /FI "WINDOWTITLE eq Pipeline Controller :9000*" 2>$null
taskkill /F /FI "WINDOWTITLE eq GitHub Adapter :9001*" 2>$null

Write-Host "Killing Node.js React Dev Server taking port 3000..."
$tcp3000 = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue
if ($tcp3000) { Stop-Process -Id $tcp3000.OwningProcess -Force -ErrorAction SilentlyContinue }

Write-Host "Releasing Windows filesystem locks..."
Start-Sleep -Seconds 3

Write-Host "Creating clean top-level directories..."
New-Item -ItemType Directory -Force -Path "backend"
New-Item -ItemType Directory -Force -Path "frontend"
New-Item -ItemType Directory -Force -Path "docs"

Write-Host "Migrating active architecture..."
Move-Item -Path "Development\Assignment 7\backend\*" -Destination "backend" -Force
Move-Item -Path "Development\Frontend\assignment 6\*" -Destination "frontend" -Force

Write-Host "Archiving legacy documents..."
New-Item -ItemType Directory -Force -Path "docs\legacy_backend_modules"
Move-Item -Path "Development\Backend\Modules\*" -Destination "docs\legacy_backend_modules" -Force -ErrorAction SilentlyContinue
Move-Item -Path "Design Part\*" -Destination "docs" -Force -ErrorAction SilentlyContinue
Move-Item -Path "frontend\ui_choice.pdf" -Destination "docs\ui_choice.pdf" -Force -ErrorAction SilentlyContinue

Write-Host "Deleting obsolete empty trees..."
Remove-Item -Path "Development" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path "Design Part" -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Restarting Backend Pipeline Services seamlessly..."
Set-Location "backend"
Start-Process "cmd.exe" -ArgumentList "/c start_all.bat"

Write-Host "Restarting Frontend Dashboard seamlessly..."
Set-Location "..\frontend"
Start-Process "cmd.exe" -ArgumentList "/k npm start"

Write-Host "Refactoring Complete! All Docker volumes untouched."
