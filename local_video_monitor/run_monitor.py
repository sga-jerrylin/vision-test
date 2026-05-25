import os
import subprocess
import sys

os.environ["MINICPMO_RTSP_URL"] = "rtsp://192.168.1.12"
os.environ["MINICPMO_WECHAT_WEBHOOK_URL"] = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=26bc9425-d542-4f90-890d-cb8e23bb1666"
os.environ["MINICPMO_INFERENCE_URL"] = "http://127.0.0.1:9060"
os.environ["MINICPMO_MONITOR_PORT"] = "8099"

subprocess.run([sys.executable, "-X", "utf8", "server.py"], cwd=os.path.dirname(os.path.abspath(__file__)))
