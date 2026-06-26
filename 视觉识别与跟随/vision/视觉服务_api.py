"""阶段九视觉 FastAPI 服务。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from .可视化_visualizer import encode_jpeg, make_placeholder_frame
from .视觉引擎_vision_engine import VisionEngine


class SelectTargetRequest(BaseModel):
    x: int
    y: int
    w: int
    h: int


def create_app(config: dict[str, Any], base_dir: str | Path | None = None, engine: VisionEngine | None = None, auto_start: bool = True) -> FastAPI:
    root = Path(base_dir or ".").resolve()
    vision_engine = engine or VisionEngine(config, root)
    app = FastAPI(title="机械臂视觉识别与跟随服务")

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
            "service": "arm_vision_api",
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

    @app.post("/target/select")
    async def select_target(req: SelectTargetRequest) -> dict[str, Any]:
        return vision_engine.select_manual_target((req.x, req.y, req.w, req.h))

    @app.post("/target/reset")
    async def reset_target() -> dict[str, Any]:
        return vision_engine.reset_manual_target()

    @app.get("/target/state")
    async def target_state() -> dict[str, Any]:
        return vision_engine.get_target_state()

    @app.get("/frame.jpg")
    async def frame_jpg() -> Response:
        content = vision_engine.store.latest_frame_bytes()
        if content is None:
            frame = make_placeholder_frame("no frame")
            content = encode_jpeg(frame)
        return Response(content=content or b"", media_type="image/jpeg")

    @app.get("/debug", response_class=HTMLResponse)
    async def debug_page() -> str:
        return """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>机械臂视觉调试</title>
  <style>
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #111; color: #eee; }
    main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 16px; padding: 16px; min-height: 100vh; box-sizing: border-box; }
    .video { display: grid; place-items: center; background: #000; border: 1px solid #333; border-radius: 8px; overflow: hidden; }
    img { width: 100%; max-height: calc(100vh - 34px); object-fit: contain; }
    aside { background: #1b1b1b; border: 1px solid #333; border-radius: 8px; padding: 14px; overflow: auto; }
    h1 { font-size: 18px; margin: 0 0 12px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; }
    .item { background: #262626; border-radius: 6px; padding: 8px; }
    .label { color: #aaa; font-size: 12px; }
    .value { font-size: 18px; margin-top: 2px; }
    pre { white-space: pre-wrap; word-break: break-word; background: #0d0d0d; border-radius: 6px; padding: 10px; font-size: 12px; }
    .ok { color: #79d279; }
    .warn { color: #ffcc66; }
    @media (max-width: 900px) { main { grid-template-columns: 1fr; } aside { max-height: none; } }
  </style>
</head>
<body>
  <main>
    <section class="video">
      <img id="frame" src="/frame.jpg" alt="latest vision frame">
    </section>
    <aside>
      <h1>视觉调试</h1>
      <div class="grid">
        <div class="item"><div class="label">detected</div><div id="detected" class="value">-</div></div>
        <div class="item"><div class="label">fps</div><div id="fps" class="value">-</div></div>
        <div class="item"><div class="label">direction</div><div id="direction" class="value">-</div></div>
        <div class="item"><div class="label">dead zone</div><div id="dead" class="value">-</div></div>
        <div class="item"><div class="label">ndx</div><div id="ndx" class="value">-</div></div>
        <div class="item"><div class="label">ndy</div><div id="ndy" class="value">-</div></div>
        <div class="item"><div class="label">smooth x</div><div id="sndx" class="value">-</div></div>
        <div class="item"><div class="label">smooth y</div><div id="sndy" class="value">-</div></div>
        <div class="item"><div class="label">follow</div><div id="follow" class="value">-</div></div>
        <div class="item"><div class="label">step count</div><div id="stepCount" class="value">-</div></div>
      </div>
      <pre id="raw">{}</pre>
    </aside>
  </main>
  <script>
    const frame = document.getElementById("frame");
    const raw = document.getElementById("raw");
    const set = (id, value, cls) => {
      const el = document.getElementById(id);
      el.textContent = value;
      el.className = "value" + (cls ? " " + cls : "");
    };
    async function readFollow() {
      try {
        const payload = await fetch("http://127.0.0.1:8010/api/v1/follow/status?ts=" + Date.now()).then(r => r.json());
        return payload && payload.ok ? payload.data : null;
      } catch (_) {
        return null;
      }
    }
    async function tick() {
      frame.src = "/frame.jpg?t=" + Date.now();
      try {
        const data = await fetch("/latest?ts=" + Date.now()).then(r => r.json());
        const follow = await readFollow();
        const off = data.offset || {};
        const sm = data.smoothed_offset || {};
        const dir = data.direction || {};
        set("detected", data.detected ? "true" : "false", data.detected ? "ok" : "warn");
        set("fps", Number(data.fps || 0).toFixed(1));
        set("direction", dir.combined || "-");
        set("dead", off.in_dead_zone ? "true" : "false", off.in_dead_zone ? "ok" : "warn");
        set("ndx", Number(off.ndx || 0).toFixed(4));
        set("ndy", Number(off.ndy || 0).toFixed(4));
        set("sndx", Number(sm.ndx || 0).toFixed(4));
        set("sndy", Number(sm.ndy || 0).toFixed(4));
        set("follow", follow ? `${follow.running ? "run" : "stop"} / ${follow.dry_run ? "dry" : "real"}` : "offline", follow && follow.running && !follow.dry_run ? "ok" : "warn");
        set("stepCount", follow ? String(follow.step_count || 0) : "-");
        raw.textContent = JSON.stringify({
          message: data.message,
          target_center: off.target_center,
          desired_center: off.desired_center,
          detector: data.detector,
          gesture: data.gesture,
          follow: follow ? {
            action: follow.last_command && follow.last_command.action,
            commands: follow.last_command && follow.last_command.commands,
            responses: follow.last_command && follow.last_command.responses,
            last_error: follow.last_error,
            effective_config: follow.effective_config,
            last_vision: follow.last_vision
          } : null
        }, null, 2);
      } catch (err) {
        raw.textContent = String(err);
      }
    }
    tick();
    setInterval(tick, 150);
  </script>
</body>
</html>
"""

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
