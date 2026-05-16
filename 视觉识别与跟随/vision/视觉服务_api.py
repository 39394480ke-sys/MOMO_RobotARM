"""阶段九视觉 FastAPI 服务。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .可视化_visualizer import make_placeholder_frame
from .视觉引擎_vision_engine import VisionEngine

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore


def create_app(config: dict[str, Any], base_dir: str | Path | None = None, engine: VisionEngine | None = None, auto_start: bool = True) -> FastAPI:
    root = Path(base_dir or ".").resolve()
    vision_engine = engine or VisionEngine(config, root)
    app = FastAPI(title="MomoAgent 阶段九视觉识别与跟随服务")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _startup() -> None:
        if auto_start:
            vision_engine.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        vision_engine.stop()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        status = vision_engine.get_status()
        return {
            "service": "momoagent_vision_api",
            "status": "ok",
            "time": time.time(),
            "running": status.get("running", False),
            "camera_available": bool((vision_engine.get_latest_result().get("camera") or {}).get("available", False)),
        }

    @app.get("/status")
    async def status() -> dict[str, Any]:
        return vision_engine.get_status()

    @app.get("/latest")
    async def latest() -> dict[str, Any]:
        result = vision_engine.get_latest_result()
        if result.get("message") == "视觉引擎还没有处理任何画面。":
            result = vision_engine.process_once()
        return result

    @app.get("/frame.jpg")
    async def frame_jpg() -> Response:
        content = vision_engine.store.latest_frame_bytes()
        if content is None:
            frame = make_placeholder_frame("no frame")
            if frame is not None and cv2 is not None:
                ok, encoded = cv2.imencode(".jpg", frame)
                if ok:
                    content = encoded.tobytes()
        return Response(content=content or b"", media_type="image/jpeg")

    @app.post("/start")
    async def start() -> dict[str, Any]:
        return {"ok": True, "status": vision_engine.start()}

    @app.post("/stop")
    async def stop() -> dict[str, Any]:
        return {"ok": True, "status": vision_engine.stop()}

    @app.websocket("/ws/stream")
    async def ws_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                await websocket.send_json({"type": "vision", "data": vision_engine.get_latest_result()})
                await asyncio.sleep(0.08)
        except WebSocketDisconnect:
            pass
        except Exception:
            try:
                await websocket.close()
            except Exception:
                pass

    app.state.vision_engine = vision_engine
    return app
