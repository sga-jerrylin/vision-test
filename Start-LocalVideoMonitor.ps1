#Requires -Version 5.1
param(
    [int]$InferencePort = 9060,
    [int]$MonitorPort = 8099,

    [int]$LlamaBatchSize = 2048,
    [int]$LlamaUBatchSize = 512,
    [int]$LlamaThreads = 8,
    [int]$LlamaThreadsBatch = 8,
    [ValidateSet("on", "off", "auto")]
    [string]$LlamaFlashAttn = "on",
    [int]$LlamaPoll = 30,
    [int]$VideoOnlyNPredict = 96,
    [int]$VideoOnlyMaxTargetLength = 256,

    [string]$WechatWebhookUrl = "",
    [string]$RtspUrl = "",
    [string]$PythonBin = "python",
    [string]$Root = $PSScriptRoot,
    [string]$CudaBin = "",
    [switch]$KeepLiveKit
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$Root = (Resolve-Path -LiteralPath $Root).Path
$CookbookDir = Join-Path $Root "repos\MiniCPM-V-CookBook\demo\web_demo\WebRTC_Demo"
$LlamaDir = Join-Path $Root "repos\llama.cpp-omni"
$ModelDir = Join-Path $Root "models\MiniCPM-o-4_5-gguf"
$CppServer = Join-Path $CookbookDir "cpp_server\minicpmo_cpp_http_server.py"
$MonitorDir = Join-Path $Root "local_video_monitor"

$LlamaBin = Join-Path $LlamaDir "build\bin\Release"
if (-not (Test-Path -LiteralPath $CppServer)) {
    throw "MiniCPM-V-CookBook wrapper not found: $CppServer. Run .\scripts\Apply-Patches.ps1 first."
}
if (-not (Test-Path -LiteralPath $LlamaDir)) {
    throw "llama.cpp-omni repo not found: $LlamaDir. Run .\scripts\Apply-Patches.ps1 first."
}
if (-not (Test-Path -LiteralPath (Join-Path $LlamaBin "llama-server.exe"))) {
    throw "llama-server.exe not found under $LlamaBin. Run .\scripts\Build-LlamaServer.ps1 first."
}
if (-not (Test-Path -LiteralPath $ModelDir)) {
    throw "Model directory not found: $ModelDir. Put MiniCPM-o 4.5 GGUF files there or pass a different -Root."
}

if ([string]::IsNullOrWhiteSpace($CudaBin)) {
    $cudaCandidates = @()
    if ($env:CUDA_PATH) { $cudaCandidates += (Join-Path $env:CUDA_PATH "bin") }
    $cudaCandidates += @(
        "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\x64",
        "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin\x64",
        "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin\x64",
        "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4\bin\x64"
    )
    $CudaBin = ($cudaCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1)
}

$pathParts = @()
if ($CudaBin -and (Test-Path -LiteralPath $CudaBin)) { $pathParts += $CudaBin }
if (Test-Path -LiteralPath $LlamaBin) { $pathParts += $LlamaBin }
if ($pathParts.Count -gt 0) {
    $env:PATH = (($pathParts -join ";") + ";" + $env:PATH)
}
$env:CUDA_VISIBLE_DEVICES = "0"
$env:VISION_BACKEND = ""
$env:MINICPMO_USE_TTS = "0"
$env:MINICPMO_USE_AUDIO_ENCODER = "0"
$env:TOKEN2WAV_DEVICE = "cpu"
$env:TTS_GPU_LAYERS = "0"
$env:LLAMA_BATCH_SIZE = "$LlamaBatchSize"
$env:LLAMA_UBATCH_SIZE = "$LlamaUBatchSize"
$env:LLAMA_THREADS = "$LlamaThreads"
$env:LLAMA_THREADS_BATCH = "$LlamaThreadsBatch"
$env:LLAMA_FLASH_ATTN = $LlamaFlashAttn
$env:LLAMA_PARALLEL = "1"
$env:LLAMA_POLL = "$LlamaPoll"
$env:MINICPMO_VIDEO_ONLY_N_PREDICT = "$VideoOnlyNPredict"
$env:MINICPMO_VIDEO_ONLY_MAX_TGT_LEN = "$VideoOnlyMaxTargetLength"
$env:MINICPMO_INFERENCE_URL = "http://127.0.0.1:$InferencePort"
$env:MINICPMO_MONITOR_PORT = "$MonitorPort"
$env:MINICPMO_WECHAT_WEBHOOK_URL = $WechatWebhookUrl
$env:MINICPMO_RTSP_URL = $RtspUrl
$env:NO_PROXY = "127.0.0.1,localhost,::1,$($env:NO_PROXY)"
$env:no_proxy = $env:NO_PROXY

function Test-HttpOk {
    param([string]$Url, [int]$TimeoutSec = 5)
    try {
        Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSec -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Stop-MatchingProcess {
    param([scriptblock]$Predicate)
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object $Predicate |
        ForEach-Object {
            try {
                Start-Process -FilePath "taskkill.exe" `
                    -ArgumentList @("/T", "/F", "/PID", "$($_.ProcessId)") `
                    -WindowStyle Hidden -Wait -ErrorAction SilentlyContinue | Out-Null
            } catch {
                # Best effort: the process may have already exited.
            }
        }
}

function Stop-PortListener {
    param([int]$Port)
    try {
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique |
            Where-Object { $_ -gt 0 } |
            ForEach-Object {
                try {
                    Start-Process -FilePath "taskkill.exe" `
                        -ArgumentList @("/T", "/F", "/PID", "$_") `
                        -WindowStyle Hidden -Wait -ErrorAction SilentlyContinue | Out-Null
                } catch {}
            }
    } catch {}
}

Write-Host "[1/3] Stopping LiveKit/demo path that is not needed..."
if (-not $KeepLiveKit) {
    try {
        if (Test-Path -LiteralPath (Join-Path $CookbookDir "docker-compose.yml")) {
            Push-Location $CookbookDir
            docker compose stop livekit 2>$null | Out-Null
            Pop-Location
        }
    } catch {
        try { Pop-Location } catch {}
    }
}
Stop-MatchingProcess {
    ($_.Name -ieq "python.exe") -and
    ($_.CommandLine -like "*local_video_monitor*server.py*")
}
Stop-PortListener -Port $MonitorPort

Write-Host "[2/3] Restarting MiniCPM-o inference in video-only mode..."
Stop-MatchingProcess {
    (($_.Name -ieq "python.exe") -and ($_.CommandLine -like "*minicpmo_cpp_http_server.py*")) -or
    (($_.Name -ieq "llama-server.exe") -and ($_.CommandLine -like "*llama.cpp-omni*"))
}

$cppOut = Join-Path $env:TEMP "minicpmo_local_cpp_server.log"
$cppErr = Join-Path $env:TEMP "minicpmo_local_cpp_server_err.log"
Remove-Item $cppOut, $cppErr -ErrorAction SilentlyContinue

$cppArgs = @(
    "-X", "utf8",
    $CppServer,
    "--llamacpp-root", $LlamaDir,
    "--model-dir", $ModelDir,
    "--port", "$InferencePort",
    "--simplex"
)
Start-Process -FilePath $PythonBin -ArgumentList $cppArgs -WindowStyle Hidden `
    -RedirectStandardOutput $cppOut -RedirectStandardError $cppErr -WorkingDirectory $LlamaDir

for ($i = 0; $i -lt 150; $i++) {
    if (Test-HttpOk "http://127.0.0.1:$InferencePort/health" 3) { break }
    Start-Sleep -Seconds 2
}
if (-not (Test-HttpOk "http://127.0.0.1:$InferencePort/health" 5)) {
    throw "Inference service did not become healthy. See $cppOut and $cppErr"
}

Write-Host "[3/3] Starting local browser-camera monitor..."
$monOut = Join-Path $env:TEMP "minicpmo_local_monitor.log"
$monErr = Join-Path $env:TEMP "minicpmo_local_monitor_err.log"
Remove-Item $monOut, $monErr -ErrorAction SilentlyContinue
Start-Process -FilePath $PythonBin -ArgumentList @("-X", "utf8", "server.py") -WindowStyle Hidden `
    -RedirectStandardOutput $monOut -RedirectStandardError $monErr -WorkingDirectory $MonitorDir

for ($i = 0; $i -lt 30; $i++) {
    if (Test-HttpOk "http://127.0.0.1:$MonitorPort/health" 3) { break }
    Start-Sleep -Seconds 1
}
if (-not (Test-HttpOk "http://127.0.0.1:$MonitorPort/health" 5)) {
    throw "Local monitor did not become healthy. See $monOut and $monErr"
}

Write-Host ""
Write-Host "MiniCPM-o local video monitor is running:"
Write-Host "  Monitor UI: http://localhost:$MonitorPort"
Write-Host "  Inference:  http://127.0.0.1:$InferencePort/health"
Write-Host "  Logs:"
Write-Host "    $cppOut"
Write-Host "    $monOut"
