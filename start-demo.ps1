# Локальный демо-запуск без Docker: бэкенд с симулятором камер (порт 8000) + интерфейс (порт 5173).
# Первый запуск: создаёт venv и ставит зависимости.
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    python -m venv (Join-Path $backend ".venv")
    & $python -m pip install -r (Join-Path $backend "requirements.txt")
}
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Push-Location (Join-Path $root "frontend"); npm install; Pop-Location
}

$env:DEMO = "1"
Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.main:app", "--port", "8000" -WorkingDirectory $backend
Push-Location (Join-Path $root "frontend")
Write-Host "Интерфейс: http://localhost:5173" -ForegroundColor Green
npm run dev
Pop-Location
