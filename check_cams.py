import cv2, hashlib, time

for ip in ["192.168.10.200", "192.168.10.221"]:
    url = f"rtsp://admin:123456@{ip}:554/h264/ch1/main/av_stream"
    cap = cv2.VideoCapture(url)
    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
    frames = []
    for i in range(5):
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
        time.sleep(0.3)
    cap.release()

    if len(frames) >= 2:
        out = f"d:/mino-vision/vision-test/cam_{ip.replace('.','_')}.jpg"
        cv2.imwrite(out, frames[2])
        h1 = hashlib.md5(frames[0].tobytes()).hexdigest()[:12]
        h2 = hashlib.md5(frames[-1].tobytes()).hexdigest()[:12]
        print(f"{ip}: {frames[2].shape[1]}x{frames[2].shape[0]}  md5_0={h1}  md5_4={h2}  diff={h1!=h2}")
    else:
        print(f"{ip}: FAIL")

# Compare 200 vs 221
print()
print("Now reading both images fresh and comparing...")
f200 = cv2.imread("d:/mino-vision/vision-test/cam_192_168_10_200.jpg")
f221 = cv2.imread("d:/mino-vision/vision-test/cam_192_168_10_221.jpg")
if f200 is not None and f221 is not None:
    same = (f200 == f221).all()
    print(f"200 vs 221 identical: {same}")
    if not same:
        diff_pixels = (f200 != f221).sum()
        print(f"Different pixels: {diff_pixels} / {f200.size} ({diff_pixels/f200.size*100:.1f}%)")
else:
    print("Could not read saved images")
