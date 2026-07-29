# Pack knight assets + bootstrap for easy Jupyter upload to RunPod pod (W2b).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$stage = Join-Path $env:TEMP "mvadapter_w2_upload"
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path (Join-Path $stage "data") | Out-Null

$mesh = Join-Path $root "model-armor-clay_repaired.glb"
if (-not (Test-Path $mesh)) {
  throw "Missing repaired mesh: $mesh"
}

Copy-Item (Join-Path $root "preview_textures\ref_gold_armor.png") (Join-Path $stage "data\ref_gold_armor.png")
Copy-Item $mesh (Join-Path $stage "data\model-armor-clay_repaired.glb")
Copy-Item (Join-Path $root "scripts\mvadapter_pod_bootstrap.sh") (Join-Path $stage "mvadapter_pod_bootstrap.sh")
Copy-Item (Join-Path $root "scripts\mvadapter_w2_oneshot.sh") (Join-Path $stage "mvadapter_w2_oneshot.sh")
$pipSetup = Join-Path $root "scripts\mvadapter_w2_pip_setup.sh"
if (Test-Path $pipSetup) {
  Copy-Item $pipSetup (Join-Path $stage "mvadapter_w2_pip_setup.sh")
}

$zip = Join-Path $root "mvadapter_w2_upload.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Write-Host "Created $zip"
Get-Item $zip | Format-List FullName, Length
