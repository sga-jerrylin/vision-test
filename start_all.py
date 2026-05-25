import os
import subprocess
import sys
import time
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = r"d:\mino-vision\vision-test"

os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ["VISION_BACKEND"] = ""
os.environ["MINICPMO_USE_TTS"] = "0"
os.environ["MINICPMO_USE_AUDIO_ENCODER"] = "0"
os.environ["TOKEN2WAV_DEVICE"] = "cpu"
os.environ["TTS_GPU_LAYERS"] = "0"
os.environ["LLAMA_BATCH_SIZE"] = "2048"
os.environ["LLAMA_UBATCH_SIZE"] = "512"
os.environ["LLAMA_THREADS"] = "8"
os.environ["LLAMA_THREADS_BATCH"] = "8"
os.environ["LLAMA_FLASH_ATTN"] = "on"
os.environ["LLAMA_PARALLEL"] = "1"
os.environ["LLAMA_POLL"] = "30"
os.environ["MINICPMO_VIDEO_ONLY_N_PREDICT"] = "96"
os.environ["MINICPMO_VIDEO_ONLY_MAX_TGT_LEN"] = "256"
os.environ["MINICPMO_INFERENCE_URL"] = "http://127.0.0.1:9060"
os.environ["MINICPMO_MONITOR_PORT"] = "8099"
os.environ["MINICPMO_WECHAT_WEBHOOK_URL"] = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=26bc9425-d542-4f90-890d-cb8e23bb1666"
os.environ["MINICPMO_RTSP_URL"] = "rtsp://192.168.10.11:554/user=admin&password=&channel=1&stream=0.sdp?"
os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
os.environ["no_proxy"] = "127.0.0.1,localhost,::1"

cuda_bin = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\x64"
llama_bin = os.path.join(ROOT, r"repos\llama.cpp-omni\build\bin\Release")
os.environ["PATH"] = f"{cuda_bin};{llama_bin};{os.environ.get('PATH', '')}"

inference_port = 9060
monitor_port = 8099

# Start inference (C++ wrapper) server
cpp_server = os.path.join(ROOT, r"repos\MiniCPM-V-CookBook\demo\web_demo\WebRTC_Demo\cpp_server\minicpmo_cpp_http_server.py")
llamacpp_root = os.path.join(ROOT, r"repos\llama.cpp-omni")
model_dir = os.path.join(ROOT, r"models\MiniCPM-o-4_5-gguf")

print("[1/2] Starting MiniCPM-o inference server...")
inf_proc = subprocess.Popen(
    [sys.executable, "-X", "utf8", cpp_server,
     "--llamacpp-root", llamacpp_root,
     "--model-dir", model_dir,
     "--port", str(inference_port),
     "--simplex"],
    cwd=llamacpp_root,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    encoding="utf-8", errors="replace"
)

# Monitor inference startup log
import threading
def log_inference():
    for line in inf_proc.stdout:
        print(f"[INF] {line.rstrip()}", flush=True)
threading.Thread(target=log_inference, daemon=True).start()

# Wait for inference health
print("Waiting for inference server...")
for i in range(180):
    try:
        import urllib.request
        urllib.request.urlopen(f"http://127.0.0.1:{inference_port}/health", timeout=5)
        print(f"Inference server ready after {i+1}s")
        break
    except:
        if i % 10 == 0:
            print(f"  Still waiting... ({i}s)")
        time.sleep(1)
else:
    print("ERROR: Inference server did not start")
    sys.exit(1)

# Start monitor server
print("[2/2] Starting local video monitor...")
monitor_dir = os.path.join(ROOT, "local_video_monitor")
mon_proc = subprocess.Popen(
    [sys.executable, "-X", "utf8", "server.py"],
    cwd=monitor_dir,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    encoding="utf-8", errors="replace"
)

def log_monitor():
    for line in mon_proc.stdout:
        print(f"[MON] {line.rstrip()}", flush=True)
threading.Thread(target=log_monitor, daemon=True).start()

# Wait for monitor health
print("Waiting for monitor server...")
for i in range(30):
    try:
        import urllib.request
        urllib.request.urlopen(f"http://127.0.0.1:{monitor_port}/health", timeout=5)
        print(f"Monitor server ready after {i+1}s")
        break
    except:
        time.sleep(1)
else:
    print("ERROR: Monitor server did not start")
    sys.exit(1)

print("")
print("=" * 60)
print("MiniCPM-o Local Video Monitor is running!")
print(f"  Monitor UI: http://localhost:{monitor_port}")
print(f"  Inference:  http://127.0.0.1:{inference_port}/health")
print(f"  RTSP:       {os.environ['MINICPMO_RTSP_URL']}")
print(f"  Webhook:    configured")
print("=" * 60)

try:
    inf_proc.wait()
except KeyboardInterrupt:
    print("Shutting down...")
    inf_proc.terminate()
    mon_proc.terminate()
