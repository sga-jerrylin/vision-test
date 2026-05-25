#Requires -Version 5.1
param(
    [int]$MonitorPort = 8099,
    [switch]$KeepInference
)

$ErrorActionPreference = "Stop"

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

Write-Host "Stopping local video monitor..."
Stop-MatchingProcess {
    ($_.Name -ieq "python.exe") -and
    ($_.CommandLine -like "*local_video_monitor*server.py*")
}
Stop-PortListener -Port $MonitorPort

if (-not $KeepInference) {
    Write-Host "Stopping MiniCPM-o inference..."
    Stop-MatchingProcess {
        (($_.Name -ieq "python.exe") -and ($_.CommandLine -like "*minicpmo_cpp_http_server.py*")) -or
        (($_.Name -ieq "llama-server.exe") -and ($_.CommandLine -like "*llama.cpp-omni*"))
    }
}

Write-Host "Stopped."
