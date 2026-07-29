param(
    [string]$ImageUrl = "",
    [string]$ImageFile = "preview_textures\ref_gold_armor.png"
)

# Track A: upload ref to R2 (if needed), then batch TRELLIS.2 clay seeds.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Missing venv: $py" }

$batchArgs = @(
    "scripts\batch_seeds_trellis2.py",
    "--seeds", "1", "7", "42", "123",
    "--texture-mode", "clay",
    "--out-prefix", "model-armor-clay-seed"
)

if ($ImageUrl) {
    Write-Host "IMAGE_URL=$ImageUrl" -ForegroundColor Green
    $batchArgs += @("--image-url", $ImageUrl)
} else {
    Write-Host "=== Upload + batch via --image-file (needs R2 creds in .env) ===" -ForegroundColor Cyan
    $batchArgs += @("--image-file", $ImageFile)
}

Write-Host ""
Write-Host "=== Batch clay seeds ===" -ForegroundColor Cyan
& $py @batchArgs

Write-Host ""
Write-Host "Done. Compare wireframes in scripts/preview_glb_local.html" -ForegroundColor Green
