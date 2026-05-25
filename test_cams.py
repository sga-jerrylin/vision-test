import cv2, requests

# 1. Test HTTP access
for ip in ["192.168.10.200", "192.168.10.221"]:
    for port in [80, 8000]:
        try:
            r = requests.get(f"http://{ip}:{port}", timeout=5)
            print(f"HTTP {ip}:{port} -> {r.status_code}, Server: {r.headers.get('Server','?')}")
        except Exception as e:
            print(f"HTTP {ip}:{port} -> {type(e).__name__}")

print()

# 2. Test RTSP with all known Hikvision formats
passwords = ["", "admin", "12345", "123456", "hik12345", "hikvision"]
paths = [
    "/Streaming/Channels/101",
    "/Streaming/Channels/102", 
    "/h264/ch1/main/av_stream",
    "/h264/ch1/sub/av_stream",
    "/ISAPI/Streaming/channels/101",
    "/ch1/main/av_stream",
]

for ip in ["192.168.10.200", "192.168.10.221"]:
    for port in [554, 8000]:
        for pwd in passwords:
            pw = f":{pwd}" if pwd else ""
            for path in paths:
                url = f"rtsp://admin{pw}@{ip}:{port}{path}"
                cap = cv2.VideoCapture(url)
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret:
                        print(f"OK  {url} -> {frame.shape[1]}x{frame.shape[0]}")
                        cap.release()
                        break
                cap.release()
            else:
                continue
            break
        else:
            continue
        break
    else:
        print(f"{ip}: all RTSP tests FAILED - RTSP might be disabled in camera settings")
