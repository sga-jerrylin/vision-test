@echo off
setlocal

echo === Step 1: Setup VS 2019 Environment ===
call "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if %ERRORLEVEL% neq 0 (
    echo ERROR: vcvars64.bat failed
    exit /b 1
)

echo === Step 2: Setup CUDA Environment ===
set "CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2"
set "PATH=%CUDA_PATH%\bin\x64;%CUDA_PATH%\bin;%PATH%"
nvcc --version
if %ERRORLEVEL% neq 0 (
    echo ERROR: nvcc not found
    exit /b 1
)

echo === Step 3: Clean old build directory ===
set "BUILD_DIR=D:\mino-vision\vision-test\repos\llama.cpp-omni\build"
if exist "%BUILD_DIR%" (
    echo Removing %BUILD_DIR% ...
    rmdir /s /q "%BUILD_DIR%"
)

echo === Step 4: CMake Configure ===
set "CMAKE_EXE=C:\Program Files\CMake\bin\cmake.exe"
set "LLAMA_DIR=D:\mino-vision\vision-test\repos\llama.cpp-omni"

"%CMAKE_EXE%" -S "%LLAMA_DIR%" -B "%BUILD_DIR%" ^
    -G "NMake Makefiles" ^
    -DGGML_CUDA=ON ^
    -DGGML_CUDA_FA=ON ^
    -DLLAMA_CURL=OFF ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DCMAKE_CUDA_FLAGS="-Xcompiler=/Zc:preprocessor" ^
    -DCUDAToolkit_ROOT="%CUDA_PATH%"

if %ERRORLEVEL% neq 0 (
    echo ERROR: CMake configure failed
    exit /b 1
)

echo === Step 5: Build llama-server ===
cd /d "%BUILD_DIR%"
nmake llama-server

if %ERRORLEVEL% neq 0 (
    echo ERROR: Build failed
    exit /b 1
)

echo === DONE ===
dir "%BUILD_DIR%\bin\llama-server.exe" 2>nul
if exist "%BUILD_DIR%\bin\llama-server.exe" (
    echo llama-server.exe built successfully!
) else (
    echo Searching for llama-server.exe...
    dir /s /b "%BUILD_DIR%\llama-server.exe" 2>nul
)

endlocal
