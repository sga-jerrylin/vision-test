@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
set "CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2"
set "PATH=%CUDA_PATH%\bin;%PATH%"
set CUDA_VISIBLE_DEVICES=0
"D:\mino-vision\vision-test\repos\llama.cpp-omni\build\bin\Release\llama-server.exe" --host 127.0.0.1 --port 19063 --model "D:\mino-vision\vision-test\models\MiniCPM-o-4_5-gguf\MiniCPM-o-4_5-Q4_K_M.gguf" --ctx-size 8192 --n-gpu-layers 99 -ngl 99
endlocal
