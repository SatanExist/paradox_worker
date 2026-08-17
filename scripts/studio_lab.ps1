# Start local Studio lab API on http://127.0.0.1:8787
# Uses .venv-studio (working ctypes). The default .venv is Python 3.14.0 and
# breaks uvicorn/click after the system Python was upgraded to 3.14.6.
# Run from repo root:  .\scripts\studio_lab.ps1

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv-studio\Scripts\python.exe"
$reqFile = Join-Path $repoRoot "requirements-studio.txt"

function Test-Ctypes([string]$pythonExe) {
    & $pythonExe -c "import ctypes" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Test-StudioDeps([string]$pythonExe) {
    & $pythonExe -c "import fastapi, uvicorn, dotenv, requests, boto3" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating .venv-studio from py -3.14 ..." -ForegroundColor Yellow
    py -3.14 -m venv .venv-studio
}

if (-not (Test-Ctypes $venvPython)) {
    Write-Error @"
.venv-studio cannot import ctypes.
Recreate with a working interpreter:
  py -3.14 -m venv --clear .venv-studio
  .\.venv-studio\Scripts\python.exe -m pip install -r requirements-studio.txt
"@
}

if (-not (Test-StudioDeps $venvPython)) {
    Write-Host "Installing requirements-studio.txt ..." -ForegroundColor Yellow
    & $venvPython -m pip install -r $reqFile
}

Write-Host ""
Write-Host "Lab:  http://127.0.0.1:8787/" -ForegroundColor Green
Write-Host "Docs: http://127.0.0.1:8787/docs" -ForegroundColor Green
Write-Host "Stop: Ctrl+C  (does not start GPU jobs by itself)" -ForegroundColor DarkGray
Write-Host ""
& $venvPython (Join-Path $repoRoot "scripts\studio_api.py")
