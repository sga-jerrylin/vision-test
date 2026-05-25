import asyncio
import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import httpx
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def strip_data_url(value: str) -> str:
    if not value:
        return ""
    marker = "base64,"
    if marker in value:
        return value.split(marker, 1)[1]
    return value


def looks_like_no_event(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    if len(cleaned) < 4:
        return True
    if cleaned.count("?") > len(cleaned) * 0.3:
        return True
    upper = cleaned.upper()
    no_event_tokens = (
        "NO_EVENT", "NO EVENT", "NOEVENT",
        "无事件", "没有事件", "没有发现", "未发现", "未检测",
        "无人", "无人在", "没有人", "没发现人", "看不到人",
        "画面中无", "画面中没有", "未触发", "无异常",
        "一切正常", "正常画面", "空画面",
    )
    return any(token in upper or token in cleaned for token in no_event_tokens)


def compact_event_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = text.replace("NO_EVENT", "").strip()
    return text[:900]


def build_assistant_prompt(rule: str) -> str:
    rule = (rule or "").strip()
    if not rule:
        rule = "有人出现在画面里就通知我，并说明性别、衣着、明显特征和移动方向。"
    return (
        "<|im_start|>system\n"
        "你是一个本机实时视频监控助手。你只能根据当前视频帧判断，不要编造看不到的细节。\n"
        "如果用户规则被触发，请用简体中文输出一条短告警，包含：发生了什么、人数、可见性别倾向、衣着、明显特征、移动方向。\n"
        "如果没有触发规则，或者画面里无法确定，请只输出：NO_EVENT。\n"
        f"用户规则：{rule}\n"
        "<|im_end|>\n"
        "<|im_start|>user\n"
        "请检查当前画面是否触发用户规则。\n"
    )


def build_frame_prompt(rule: str, cam_label: str = "") -> str:
    rule = (rule or "").strip()
    if not rule:
        rule = "有人出现在画面里就通知我，并说明性别、衣着、明显特征和移动方向。"
    cam_hint = f"当前摄像头：{cam_label}。" if cam_label else ""
    return (
        "\n请只基于当前这一帧摄像头画面判断是否触发以下用户规则。\n"
        f"{cam_hint}"
        f"用户规则：{rule}\n"
        "输出要求：\n"
        "  - 如果画面触发了用户规则，请输出一条简短中文告警，包含：发生了什么事、人数、衣着、特征、移动方向。\n"
        "  - 如果没有触发规则或看不清，请只输出 NO_EVENT，不要输出任何其他内容。\n"
    )


class StartRequest(BaseModel):
    rule: str = Field(default="")
    webhook_url: Optional[str] = Field(default=None)
    rtsp_url: Optional[str] = Field(default=None)
    rtsp_urls: Optional[list[str]] = Field(default=None)
    cam_labels: Optional[list[str]] = Field(default=None)
    high_quality: bool = Field(default=False)
    generate_interval_sec: float = Field(default=0.9, ge=0.2, le=10)
    notify_cooldown_sec: float = Field(default=12.0, ge=0, le=3600)


class FrameRequest(BaseModel):
    image: str
    ts: Optional[float] = None


class TestWebhookRequest(BaseModel):
    message: str = "MiniCPM-o local video monitor webhook test"
    webhook_url: Optional[str] = None


def bgr_to_jpeg_base64(frame: np.ndarray, quality: int = 72) -> str:
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    success, buffer = cv2.imencode(".jpg", frame, encode_params)
    if not success:
        return ""
    return base64.b64encode(buffer).decode("ascii")


class RTSPCapture:
    def __init__(self, rtsp_url: str, width: int = 768):
        self.rtsp_url = rtsp_url
        self.width = width
        self.cap: Optional[cv2.VideoCapture] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.latest_frame_b64: str = ""
        self.latest_preview_b64: str = ""
        self.latest_preview_small: bytes = b""
        self.latest_timestamp: float = 0.0
        self.frame_lock = threading.Lock()
        self.fps_counter = 0
        self.fps_timer = time.time()
        self.current_fps = 0.0

    def start(self) -> None:
        if self.running:
            return
        self.cap = cv2.VideoCapture(self.rtsp_url)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.cap.isOpened():
            raise RuntimeError(f"无法打开 RTSP 流: {self.rtsp_url}")
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        print(f"[RTSP] 已连接摄像头: {self.rtsp_url}")

    def stop(self) -> None:
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=3.0)
            self.thread = None
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        print("[RTSP] 摄像头已断开")

    def _capture_loop(self) -> None:
        last_t = 0.0
        while self.running and self.cap is not None:
            ret, frame = self.cap.read()
            if not ret:
                print("[RTSP] 读取帧失败，尝试重连...")
                time.sleep(1.0)
                continue
            now_t = time.time()
            if now_t - last_t < 0.18:
                continue
            last_t = now_t
            h, w = frame.shape[:2]
            small_h, small_w = (480, 270)
            preview_small = cv2.resize(frame, (small_w, small_h), interpolation=cv2.INTER_AREA)
            _, preview_small_bytes = cv2.imencode(".jpg", preview_small, [cv2.IMWRITE_JPEG_QUALITY, 40])
            scale = min(1.0, self.width / w)
            if scale < 1.0:
                new_w = int(w * scale)
                new_h = int(h * scale)
                small = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            else:
                small = frame
            infer_b64 = bgr_to_jpeg_base64(small, quality=82)
            with self.frame_lock:
                self.latest_frame_b64 = infer_b64
                self.latest_preview_b64 = bgr_to_jpeg_base64(frame, quality=88)
                self.latest_preview_small = preview_small_bytes.tobytes()
                self.latest_timestamp = time.time()
            self.fps_counter += 1
            elapsed = now_t - self.fps_timer
            if elapsed >= 5.0:
                self.current_fps = self.fps_counter / elapsed
                self.fps_counter = 0
                self.fps_timer = now_t

    def get_frame(self) -> tuple[str, float]:
        with self.frame_lock:
            return self.latest_frame_b64, self.latest_timestamp

    def get_preview_frame(self) -> tuple[str, float]:
        with self.frame_lock:
            return self.latest_preview_b64, self.latest_timestamp


@dataclass
class MonitorState:
    inference_url: str
    webhook_url: str = ""
    rtsp_url: str = ""
    active: bool = False
    initialized: bool = False
    busy: bool = False
    rule: str = ""
    session_id: str = ""
    frame_id: int = 0
    processed_frames: int = 0
    skipped_frames: int = 0
    events_sent: int = 0
    last_generate_at: float = 0.0
    last_notify_at: float = 0.0
    last_event_text: str = ""
    last_notified_event_text: str = ""
    last_analysis: str = ""
    high_quality: bool = False
    generate_interval_sec: float = 0.9
    notify_cooldown_sec: float = 12.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    client: Optional[httpx.AsyncClient] = None
    rtsp_capture: Optional["RTSPCapture"] = None
    multi_cam: bool = False
    rtsp_urls: list = field(default_factory=list)
    cam_labels: list = field(default_factory=list)
    rtsp_captures: list = field(default_factory=list)
    current_cam_index: int = 0
    session_frame_count: int = 0


state = MonitorState(
    inference_url=os.environ.get("MINICPMO_INFERENCE_URL", "http://127.0.0.1:9060").rstrip("/"),
    webhook_url=os.environ.get("MINICPMO_WECHAT_WEBHOOK_URL", "").strip(),
    rtsp_url=os.environ.get("MINICPMO_RTSP_URL", "").strip(),
)

WARMUP_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)

app = FastAPI(title="MiniCPM-o Local Video Monitor", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
async def startup() -> None:
    timeout = httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0)
    state.client = httpx.AsyncClient(timeout=timeout, trust_env=False)


@app.on_event("shutdown")
async def shutdown() -> None:
    if state.client is not None:
        await state.client.aclose()


async def client() -> httpx.AsyncClient:
    if state.client is None:
        timeout = httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0)
        state.client = httpx.AsyncClient(timeout=timeout, trust_env=False)
    return state.client


async def init_model(rule: str, high_quality: bool) -> dict:
    payload = {
        "media_type": "omni",
        "duplex_mode": False,
        "high_quality_mode": high_quality,
        "high_fps_mode": True,
        "language": "zh",
        "use_audio": False,
        "use_tts": False,
        "task_prompt_text": rule,
        "assistant_prompt": build_assistant_prompt(rule),
    }
    http = await client()
    response = await http.post(f"{state.inference_url}/omni/init_sys_prompt", json=payload)
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"model init failed: {response.text}")
    data = response.json()
    state.session_id = str(data.get("session_id") or "")
    state.initialized = True
    await warmup_system_prompt()
    return data


async def warmup_system_prompt() -> None:
    if not state.session_id:
        return
    payload = {
        "image": WARMUP_IMAGE_B64,
        "image_audio_id": 0,
        "frame_index": 0,
        "session_id": state.session_id,
        "prompt": "",
    }
    http = await client()
    response = await http.post(f"{state.inference_url}/omni/streaming_prefill", json=payload)
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"warmup prefill failed: {response.text}")


async def prefill_frame(image_b64: str, cam_label: str = "") -> dict:
    state.frame_id += 1
    payload = {
        "image": strip_data_url(image_b64),
        "prompt": build_frame_prompt(state.rule, cam_label),
        "image_audio_id": state.frame_id,
        "frame_index": 0,
        "session_id": state.session_id,
    }
    http = await client()
    response = await http.post(f"{state.inference_url}/omni/streaming_prefill", json=payload)
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"prefill failed: {response.text}")
    return response.json()


def parse_sse_text(raw: str) -> str:
    parts: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        chunk = event.get("chunk_data")
        if isinstance(chunk, dict) and chunk.get("text"):
            parts.append(str(chunk["text"]))
        elif event.get("text"):
            parts.append(str(event["text"]))
        elif event.get("content"):
            parts.append(str(event["content"]))
        elif event.get("error"):
            parts.append(f"ERROR: {event['error']}")
    return "".join(parts).strip()


async def generate_text() -> str:
    payload = {
        "session_id": state.session_id,
        "mode": "simplex",
        "stream": True,
    }
    http = await client()
    response = await http.post(f"{state.inference_url}/omni/streaming_generate", json=payload)
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"generate failed: {response.text}")
    raw = response.content
    try:
        sse_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        sse_text = raw.decode("gbk", errors="replace")
    text = parse_sse_text(sse_text)
    return text or "NO_EVENT"


async def send_wechat_webhook(text: str, webhook_url: str) -> dict:
    webhook_url = (webhook_url or "").strip()
    if not webhook_url:
        return {"sent": False, "reason": "webhook_url_empty"}
    payload = {
        "msgtype": "text",
        "text": {"content": text},
    }
    http = await client()
    response = await http.post(webhook_url, json=payload, timeout=15.0)
    try:
        data = response.json()
    except Exception:
        data = {"status_code": response.status_code, "text": response.text[:300]}
    return {"sent": response.status_code == 200, "response": data}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict:
    rtsp_alive = state.rtsp_capture is not None and state.rtsp_capture.running
    return {
        "status": "healthy",
        "service": "local-video-monitor",
        "active": state.active,
        "initialized": state.initialized,
        "busy": state.busy,
        "inference_url": state.inference_url,
        "processed_frames": state.processed_frames,
        "skipped_frames": state.skipped_frames,
        "events_sent": state.events_sent,
        "rtsp_connected": rtsp_alive,
        "rtsp_url": state.rtsp_url if rtsp_alive else "",
    }


PREVIEW_EXECUTOR = ThreadPoolExecutor(max_workers=4)


@app.get("/api/preview_monitor")
async def preview_monitor():
    if state.rtsp_capture is None or not state.rtsp_capture.running:
        raise HTTPException(status_code=404, detail="no rtsp stream active")

    async def generate():
        boundary = "--frame"
        while state.rtsp_capture is not None and state.rtsp_capture.running:
            with state.rtsp_capture.frame_lock:
                buf = state.rtsp_capture.latest_preview_small
            if buf:
                yield f"{boundary}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(buf)}\r\n\r\n".encode() + buf + b"\r\n"
            await asyncio.sleep(0.06)
        yield f"{boundary}--\r\n".encode()

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/preview_cap/{idx}")
async def preview_cap(idx: int):
    if idx < 0 or idx >= len(state.rtsp_captures):
        raise HTTPException(status_code=404, detail="capture index out of range")
    cap_obj = state.rtsp_captures[idx]

    async def generate():
        boundary = "--frame"
        while state.active and cap_obj.running:
            with cap_obj.frame_lock:
                buf = cap_obj.latest_preview_small
            if buf:
                yield f"{boundary}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(buf)}\r\n\r\n".encode() + buf + b"\r\n"
            await asyncio.sleep(0.08)
        yield f"{boundary}--\r\n".encode()

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/preview")
async def preview_stream(url: str = ""):
    if url:
        cap = cv2.VideoCapture(url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
        if not cap.isOpened():
            cap.release()
            raise HTTPException(status_code=404, detail="cannot open RTSP stream")

        loop = asyncio.get_event_loop()

        async def generate():
            nonlocal cap
            boundary = "--frame"
            preview_w = 640
            skip = 0
            try:
                while True:
                    ret, frame = await loop.run_in_executor(PREVIEW_EXECUTOR, cap.read)
                    if not ret:
                        break
                    skip += 1
                    if skip % 3 != 0:
                        continue
                    h, w = frame.shape[:2]
                    if w > preview_w:
                        scale = preview_w / w
                        frame = cv2.resize(frame, (preview_w, int(h * scale)), interpolation=cv2.INTER_AREA)
                    _, buf = await loop.run_in_executor(PREVIEW_EXECUTOR, cv2.imencode, ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
                    yield f"{boundary}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(buf)}\r\n\r\n".encode()
                    yield buf.tobytes()
                    yield b"\r\n"
                    await asyncio.sleep(0.06)
            finally:
                yield f"{boundary}--\r\n".encode()
                cap.release()

        return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")

    if state.rtsp_capture is None or not state.rtsp_capture.running:
        raise HTTPException(status_code=404, detail="no rtsp stream active")

    async def generate():
        boundary = "--frame"
        while state.rtsp_capture is not None and state.rtsp_capture.running:
            b64, _ = state.rtsp_capture.get_preview_frame()
            if b64:
                frame_bytes = base64.b64decode(b64)
                yield f"{boundary}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame_bytes)}\r\n\r\n".encode()
                yield frame_bytes
                yield b"\r\n"
            await asyncio.sleep(0.05)
        yield f"{boundary}--\r\n".encode()

    return StreamingResponse(generate(), media_type=f"multipart/x-mixed-replace; boundary=frame")


@app.get("/api/state")
async def get_state() -> dict:
    rtsp_alive = state.rtsp_capture is not None and state.rtsp_capture.running
    return {
        "active": state.active,
        "initialized": state.initialized,
        "busy": state.busy,
        "rule": state.rule,
        "session_id": state.session_id,
        "frame_id": state.frame_id,
        "processed_frames": state.processed_frames,
        "skipped_frames": state.skipped_frames,
        "events_sent": state.events_sent,
        "last_analysis": state.last_analysis,
        "last_event_text": state.last_event_text,
        "last_notified_event_text": state.last_notified_event_text,
        "webhook_configured": bool(state.webhook_url),
        "inference_url": state.inference_url,
        "rtsp_connected": rtsp_alive,
        "rtsp_url": state.rtsp_url if rtsp_alive else "",
    }


SESSION_RESET_EVERY = 40


async def reset_session() -> None:
    try:
        http = await client()
        await http.post(f"{state.inference_url}/omni/stop", timeout=10.0)
    except Exception:
        pass
    state.initialized = False
    state.session_id = ""
    state.session_frame_count = 0
    await init_model(state.rule, state.high_quality)


async def process_frame_internal(image_b64: str, cam_label: str = "") -> dict:
    if state.lock.locked():
        state.skipped_frames += 1
        return {"status": "skipped_busy"}
    now = time.time()
    if state.last_generate_at and (now - state.last_generate_at) < state.generate_interval_sec:
        return {"status": "skipped_interval"}
    result = {}
    async with state.lock:
        state.busy = True
        try:
            await prefill_frame(image_b64, cam_label)
            state.last_generate_at = time.time()
            text = await generate_text()
            state.processed_frames += 1
            state.session_frame_count += 1
            state.last_analysis = text
            if looks_like_no_event(text):
                result = {"status": "no_event", "analysis": text}
            else:
                event_text = compact_event_text(text)
                state.last_event_text = event_text
                if state.webhook_url:
                    now_t = time.time()
                    if state.notify_cooldown_sec > 0 and state.last_notify_at > 0:
                        if (now_t - state.last_notify_at) < state.notify_cooldown_sec:
                            result = {"status": "event", "analysis": event_text, "notify": {"sent": False, "reason": "cooldown"}}
                    if not result:
                        content = (
                            "MiniCPM-o 本机视频监控告警\n"
                            f"规则：{state.rule}\n"
                            f"{cam_label + '：' if cam_label else ''}{event_text}"
                        )
                        notify_result = await send_wechat_webhook(content, state.webhook_url)
                        state.last_notify_at = now_t
                        if notify_result.get("sent"):
                            state.events_sent += 1
                        state.last_notified_event_text = event_text
                        result = {
                            "status": "event",
                            "analysis": event_text,
                            "notify": notify_result,
                        }
                else:
                    notify_result = {"sent": False, "reason": "webhook_url_empty"}
                    result = {
                        "status": "event",
                        "analysis": event_text,
                        "notify": notify_result,
                    }
        finally:
            state.busy = False
    if state.session_frame_count >= SESSION_RESET_EVERY:
        print(f"[Session] 已处理 {state.session_frame_count} 帧，重置 session 释放显存...")
        await reset_session()
    return result


async def rtsp_processing_loop() -> None:
    print("[RTSP] 后台帧处理循环已启动")
    while state.active and state.rtsp_capture is not None:
        if not state.initialized:
            await asyncio.sleep(0.5)
            continue
        image_b64, ts = state.rtsp_capture.get_frame()
        if not image_b64:
            await asyncio.sleep(0.3)
            continue
        result = await process_frame_internal(image_b64)
        status = result.get("status", "unknown")
        if status == "event":
            print(f"[RTSP] 检测到事件: {result.get('analysis', '')[:120]}")
        elif status == "no_event":
            pass
        elif status == "skipped_interval":
            pass
        elif status == "skipped_busy":
            print("[RTSP] 推理繁忙，跳帧")
        interval = max(0.2, state.generate_interval_sec)
        await asyncio.sleep(interval)


async def multi_rtsp_loop() -> None:
    print("[RTSP] 多路帧处理循环已启动")
    while state.active and state.rtsp_captures:
        if not state.initialized:
            await asyncio.sleep(0.5)
            continue
        idx = state.current_cam_index % len(state.rtsp_captures)
        cap = state.rtsp_captures[idx]
        lbl = state.cam_labels[idx] if idx < len(state.cam_labels) else f"Cam{idx+1}"
        image_b64, ts = cap.get_frame()
        if image_b64:
            result = await process_frame_internal(image_b64, lbl)
            status = result.get("status", "unknown")
            if status == "event":
                analysis = result.get("analysis", "")[:120]
                print(f"[RTSP] [{lbl}] 检测到事件: {analysis}")
            elif status == "no_event":
                pass
            elif status == "skipped_interval":
                pass
            elif status == "skipped_busy":
                print(f"[RTSP] [{lbl}] 推理繁忙，跳帧")
        state.current_cam_index += 1
        interval = max(0.3, state.generate_interval_sec / len(state.rtsp_captures))
        await asyncio.sleep(interval)


@app.post("/api/start")
async def start_monitoring(request: StartRequest) -> dict:
    rule = request.rule.strip() or "有人出现在画面里就通知我，并说明性别、衣着、明显特征和移动方向。"
    state.rule = rule
    if request.webhook_url is not None:
        state.webhook_url = request.webhook_url.strip()
    state.high_quality = request.high_quality
    state.generate_interval_sec = request.generate_interval_sec
    state.notify_cooldown_sec = request.notify_cooldown_sec
    state.active = True
    state.initialized = False
    state.frame_id = 0
    state.processed_frames = 0
    state.skipped_frames = 0
    state.events_sent = 0
    state.session_frame_count = 0
    state.last_analysis = ""
    state.last_event_text = ""
    state.last_notified_event_text = ""
    state.last_generate_at = 0.0
    state.last_notify_at = 0.0

    rtsp_url = (request.rtsp_url or "").strip()
    rtsp_urls = request.rtsp_urls or []
    cam_labels = request.cam_labels or []
    if len(rtsp_urls) > 1:
        state.multi_cam = True
        state.rtsp_urls = rtsp_urls
        state.cam_labels = cam_labels
        state.current_cam_index = 0
    else:
        state.multi_cam = False
        if rtsp_url:
            state.rtsp_url = rtsp_url
    if state.rtsp_capture is not None:
        state.rtsp_capture.stop()
        state.rtsp_capture = None
    for c in state.rtsp_captures:
        c.stop()
    state.rtsp_captures = []

    init_result = await init_model(rule, request.high_quality)

    rtsp_started = False
    if state.multi_cam:
        all_ok = True
        for i, url in enumerate(state.rtsp_urls):
            try:
                cap = RTSPCapture(url, width=1024)
                cap.start()
                state.rtsp_captures.append(cap)
                lbl = state.cam_labels[i] if i < len(state.cam_labels) else f"Cam{i+1}"
                print(f"[RTSP] 多路 #{i+1} {lbl}: {url}")
            except Exception as e:
                print(f"[RTSP] 多路 #{i+1} 启动失败: {e}")
                all_ok = False
        if all_ok:
            state.rtsp_url = "multi://" + ",".join(state.rtsp_urls)
            asyncio.create_task(multi_rtsp_loop())
            rtsp_started = True
    elif state.rtsp_url:
        try:
            state.rtsp_capture = RTSPCapture(state.rtsp_url, width=1280)
            state.rtsp_capture.start()
            asyncio.create_task(rtsp_processing_loop())
            rtsp_started = True
            print(f"[RTSP] 自动帧抓取已启动: {state.rtsp_url}")
        except Exception as e:
            print(f"[RTSP] 启动失败: {e}")

    return {
        "ok": True,
        "message": "monitoring_started",
        "init": init_result,
        "webhook_configured": bool(state.webhook_url),
        "rtsp_connected": rtsp_started,
        "rtsp_url": state.rtsp_url if rtsp_started else "",
    }


@app.post("/api/stop")
async def stop_monitoring() -> dict:
    state.active = False
    state.initialized = False
    state.multi_cam = False
    if state.rtsp_capture is not None:
        state.rtsp_capture.stop()
        state.rtsp_capture = None
        print("[RTSP] 摄像头已停止")
    for c in state.rtsp_captures:
        c.stop()
    state.rtsp_captures = []
    try:
        http = await client()
        await http.post(f"{state.inference_url}/omni/stop", timeout=10.0)
    except Exception:
        pass
    return {"ok": True, "message": "monitoring_stopped"}


@app.post("/api/frame")
async def handle_frame(request: FrameRequest) -> dict:
    if not state.active:
        return {"ok": True, "status": "idle"}
    if not state.initialized:
        await init_model(state.rule, state.high_quality)
    result = await process_frame_internal(request.image)
    result["ok"] = True
    result["processed_frames"] = state.processed_frames
    if result.get("status") == "event":
        result["events_sent"] = state.events_sent
    return result


@app.post("/api/test_webhook")
async def test_webhook(request: TestWebhookRequest) -> dict:
    webhook_url = request.webhook_url or state.webhook_url
    result = await send_wechat_webhook(request.message, webhook_url)
    return {"ok": bool(result.get("sent")), "result": result}


if __name__ == "__main__":
    host = os.environ.get("MINICPMO_MONITOR_HOST", "127.0.0.1")
    port = int(os.environ.get("MINICPMO_MONITOR_PORT", "8099"))
    uvicorn.run(app, host=host, port=port, log_level=os.environ.get("LOG_LEVEL", "info"))
