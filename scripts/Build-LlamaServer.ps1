#Requires -Version 5.1
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Generator = "",
    [string]$CudaToolkitRoot = "",
    [int]$Parallel = 8
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path -LiteralPath $Root).Path
$LlamaDir = Join-Path $Root "repos\llama.cpp-omni"
$BuildDir = Join-Path $LlamaDir "build"

if (-not (Test-Path -LiteralPath $LlamaDir)) {
    throw "llama.cpp-omni not found at $LlamaDir. Run .\scripts\Apply-Patches.ps1 first."
}

$cmakeCommand = Get-Command cmake.exe -ErrorAction SilentlyContinue
$cmakeExe = if ($cmakeCommand) { $cmakeCommand.Source } else { "" }
if ([string]::IsNullOrWhiteSpace($cmakeExe)) {
    $cmakeCandidates = @(
        "C:\Program Files\CMake\bin\cmake.exe",
        "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
        "C:\Program Files\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
        "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
        "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
        "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
        "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
    )
    $cmakeExe = ($cmakeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1)
}
if ([string]::IsNullOrWhiteSpace($cmakeExe)) {
    throw "cmake.exe not found. Install CMake or Visual Studio Build Tools with C++ CMake tools."
}

$configureArgs = @(
    "-S", $LlamaDir,
    "-B", $BuildDir,
    "-DGGML_CUDA=ON",
    "-DGGML_CUDA_FA=ON",
    "-DGGML_CUDA_GRAPHS=ON",
    "-DLLAMA_CURL=OFF",
    "-DCMAKE_CUDA_FLAGS=-Xcompiler=/Zc:preprocessor",
    "-DCMAKE_BUILD_TYPE=Release"
)
if (-not [string]::IsNullOrWhiteSpace($Generator)) {
    $configureArgs += @("-G", $Generator)
}
if (-not [string]::IsNullOrWhiteSpace($CudaToolkitRoot)) {
    $configureArgs += "-DCUDAToolkit_ROOT=$CudaToolkitRoot"
}

Write-Host "Configuring llama.cpp-omni..."
& $cmakeExe @configureArgs
if ($LASTEXITCODE -ne 0) { throw "CMake configure failed." }

Write-Host "Building llama-server..."
& $cmakeExe --build $BuildDir --config Release --target llama-server --parallel $Parallel
if ($LASTEXITCODE -ne 0) { throw "CMake build failed." }

$exe = Join-Path $BuildDir "bin\Release\llama-server.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Build finished but llama-server.exe was not found at $exe"
}

Write-Host ""
Write-Host "Build finished: $exe"
