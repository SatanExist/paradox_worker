# Перед commit/push — проверка и напоминание
# Запуск: из корня репо  .\scripts\sync-end.ps1

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repoRoot

Write-Host ""
Write-Host "=== paradox_worker: sync-end ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "Git status:" -ForegroundColor Yellow
git status --short

Write-Host ""
Write-Host "Проверь перед push:" -ForegroundColor Yellow
Write-Host "  [ ] memory-bank/activeContext.md обновлён (журнал сессий, дата)"
Write-Host "  [ ] .env НЕ в списке изменений"
Write-Host ""

$activeContext = Get-Content "memory-bank\activeContext.md" -Raw
if ($activeContext -notmatch "Последнее обновление:") {
    Write-Host "WARN: не найдена дата обновления в activeContext.md" -ForegroundColor Red
}

Write-Host "Пример commit + push:" -ForegroundColor Green
Write-Host "  git add memory-bank/ worker.py"
Write-Host "  git commit -m ""Update context: кратко что сделали"""
Write-Host "  git push"
Write-Host ""
