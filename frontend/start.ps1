$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $root

Write-Host "Starting backend on http://127.0.0.1:8000 ..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "Set-Location '$projectRoot'; python -m uvicorn main:app --port 8000 --app-dir 'frontend\backend'"

Write-Host "Starting frontend on http://localhost:5173 ..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "Set-Location '$root\ui'; npm run dev"

Write-Host ""
Write-Host "Open http://localhost:5173 in your browser."
