import subprocess, sys, os, time

cuda_bin = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\x64"
os.environ["PATH"] = cuda_bin + ";" + os.environ.get("PATH", "")
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

cmd = [
    r"D:\mino-vision\vision-test\repos\llama.cpp-omni\build\bin\Release\llama-server.exe",
    "--host", "127.0.0.1",
    "--port", "19065",
    "--model", r"D:\mino-vision\vision-test\models\MiniCPM-o-4_5-gguf\MiniCPM-o-4_5-Q4_K_M.gguf",
    "--ctx-size", "8192",
    "--n-gpu-layers", "99",
    "-ngl", "99",
]

print(f"PATH has CUDA: {cuda_bin in os.environ['PATH']}", flush=True)
print(f"Running: {' '.join(cmd)}", flush=True)

proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                        encoding='utf-8', errors='replace', bufsize=1)

start = time.time()
while time.time() - start < 30:
    line = proc.stdout.readline()
    if line:
        print(f"[{int(time.time()-start)}s] {line.rstrip()}", flush=True)
    if proc.poll() is not None:
        print(f"Process exited: {proc.returncode}", flush=True)
        break

if proc.poll() is None:
    print("Process still running after 30s!", flush=True)
    proc.kill()
