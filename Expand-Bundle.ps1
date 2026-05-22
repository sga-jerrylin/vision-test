#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$BundleDir = Join-Path $Root "bundle"
$ZipPath = Join-Path $Root "vision-test-source.zip"

if (-not (Test-Path -LiteralPath $BundleDir)) {
    throw "Bundle directory not found: $BundleDir"
}

$parts = Get-ChildItem -LiteralPath $BundleDir -Filter "bundle.part*" | Sort-Object Name
if (-not $parts -or $parts.Count -eq 0) {
    throw "No bundle parts found under $BundleDir"
}

Write-Host "Combining $($parts.Count) bundle parts..."
$b64 = foreach ($part in $parts) {
    Get-Content -LiteralPath $part.FullName -Raw
}
$b64 = ($b64 -join "").Trim()

Write-Host "Writing source archive..."
[IO.File]::WriteAllBytes($ZipPath, [Convert]::FromBase64String($b64))

Write-Host "Expanding source..."
Expand-Archive -LiteralPath $ZipPath -DestinationPath $Root -Force
Remove-Item -LiteralPath $ZipPath -Force

Write-Host ""
Write-Host "Source expanded. Next:"
Write-Host "  .\scripts\Apply-Patches.ps1"
Write-Host "  .\scripts\Build-LlamaServer.ps1"
Write-Host "  .\Start-LocalVideoMonitor.ps1 -WechatWebhookUrl '<your enterprise wechat robot webhook>'"
