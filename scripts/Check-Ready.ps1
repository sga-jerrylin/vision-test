#Requires -Version 5.1
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonBin = "python"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath $Root).Path

$checks = @(
    @{ Name = "local monitor"; Path = Join-Path $Root "local_video_monitor\server.py" },
    @{ Name = "MiniCPM wrapper"; Path = Join-Path $Root "repos\MiniCPM-V-CookBook\demo\web_demo\WebRTC_Demo\cpp_server\minicpmo_cpp_http_server.py" },
    @{ Name = "llama-server.exe"; Path = Join-Path $Root "repos\llama.cpp-omni\build\bin\Release\llama-server.exe" },
    @{ Name = "model dir"; Path = Join-Path $Root "models\MiniCPM-o-4_5-gguf" }
)

foreach ($check in $checks) {
    if (Test-Path -LiteralPath $check.Path) {
        Write-Host "[OK] $($check.Name): $($check.Path)"
    } else {
        Write-Host "[MISS] $($check.Name): $($check.Path)"
    }
}

Write-Host ""
Write-Host "Python:"
& $PythonBin --version
Write-Host ""
Write-Host "If every required item is [OK], run:"
Write-Host "  .\Start-LocalVideoMonitor.ps1 -WechatWebhookUrl '<your webhook>'"

