import requests
h = requests.get("http://127.0.0.1:8099/", timeout=5).text
checks = ["startMultiPreview", "multi-cell", "position: absolute", "switchPreview", "RTSP_URLS", "encodeURIComponent"]
for x in checks:
    print("OK" if x in h else "MISS", x)
print()
print("Page size:", len(h))
