#Requires -Version 5.1
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonBin = "python",
    [switch]$SkipPipInstall
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path -LiteralPath $Root).Path
$ReposDir = Join-Path $Root "repos"
$PatchDir = Join-Path $Root "patches"
New-Item -ItemType Directory -Force -Path $ReposDir | Out-Null

$repos = @(
    @{
        Name = "llama.cpp-omni"
        Url = "https://github.com/tc-mb/llama.cpp-omni.git"
        Commit = "cebbafba1d773a80ab06b8b4dbe9d032f5a89fd2"
        Patch = Join-Path $PatchDir "llama.cpp-omni\video-frame-prompt.patch"
    },
    @{
        Name = "MiniCPM-V-CookBook"
        Url = "https://github.com/OpenSQZ/MiniCPM-V-CookBook.git"
        Commit = "d811cdc79d302fcfe183028c83cf59d0e3043020"
        Patch = Join-Path $PatchDir "MiniCPM-V-CookBook\video-wrapper-prompt.patch"
    }
)

function Invoke-Git {
    param(
        [Parameter(Mandatory=$true)][string]$WorkingDirectory,
        [Parameter(Mandatory=$true)][string[]]$Arguments
    )
    & git -C $WorkingDirectory @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed in $WorkingDirectory"
    }
}

function Ensure-Repo {
    param([hashtable]$Repo)

    $repoDir = Join-Path $ReposDir $Repo.Name
    if (-not (Test-Path -LiteralPath $repoDir)) {
        Write-Host "Cloning $($Repo.Name)..."
        & git clone $Repo.Url $repoDir
        if ($LASTEXITCODE -ne 0) { throw "git clone failed for $($Repo.Url)" }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $repoDir ".git"))) {
        throw "$repoDir exists but is not a git repository."
    }

    Write-Host "Preparing $($Repo.Name) at $($Repo.Commit)..."
    Invoke-Git $repoDir @("fetch", "origin")

    $current = (& git -C $repoDir rev-parse HEAD).Trim()
    if ($current -ne $Repo.Commit) {
        $dirty = (& git -C $repoDir status --porcelain)
        if ($dirty) {
            throw "$repoDir has local changes. Commit/stash them or use a fresh clone before applying this setup."
        }
        Invoke-Git $repoDir @("checkout", $Repo.Commit)
    }

    $patch = $Repo.Patch
    if (-not (Test-Path -LiteralPath $patch)) {
        throw "Patch not found: $patch"
    }

    & git -C $repoDir apply --check $patch 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Applying patch: $patch"
        Invoke-Git $repoDir @("apply", $patch)
        return
    }

    & git -C $repoDir apply --reverse --check $patch 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Patch already applied: $patch"
        return
    }

    throw "Patch does not apply cleanly: $patch"
}

foreach ($repo in $repos) {
    Ensure-Repo $repo
}

if (-not $SkipPipInstall) {
    $requirements = Join-Path $Root "requirements-local-monitor.txt"
    Write-Host "Installing Python requirements..."
    & $PythonBin -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed. You can rerun with -SkipPipInstall after installing requirements manually."
    }
}

Write-Host ""
Write-Host "Source setup finished."
Write-Host "Next:"
Write-Host "  1. Put MiniCPM-o 4.5 GGUF files under: $Root\models\MiniCPM-o-4_5-gguf"
Write-Host "  2. Run: .\scripts\Build-LlamaServer.ps1"
Write-Host "  3. Run: .\Start-LocalVideoMonitor.ps1 -WechatWebhookUrl '<your webhook>'"

