# Начало рабочей сессии — подтянуть контекст с GitHub
# Запуск: из корня репо  .\scripts\sync-start.ps1

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repoRoot

Write-Host ""
Write-Host "=== paradox_worker: sync-start ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/2] git pull..." -ForegroundColor Yellow
git pull

Write-Host ""
Write-Host "[2/2] Активный контекст (начало файла):" -ForegroundColor Yellow
Write-Host "----------------------------------------"
Get-Content "memory-bank\activeContext.md" -TotalCount 45
Write-Host "----------------------------------------"
Write-Host ""
Write-Host "Дальше в Cursor — новый чат:" -ForegroundColor Green
Write-Host "  @memory-bank/activeContext.md"
Write-Host ""
