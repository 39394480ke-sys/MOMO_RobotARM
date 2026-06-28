"""dry-run 视觉跟随 + J10 导轨运镜测试。

需要先启动 Web API。测试会启动一个本地 fake latest 服务，不访问真实摄像头或舵机。
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from Web测试客户端_test_client import connect_dry_run, get_json, post_json


class LatestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        payload = {
            "detected": True,
            "smoothed_offset": {"valid": True, "ndx": 0.2, "ndy": -0.2},
            "offset": {"in_dead_zone": False},
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), LatestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    latest_url = f"http://127.0.0.1:{server.server_port}/latest"
    try:
        connect_dry_run()
        started = post_json(
            "/api/v1/follow/start",
            {
                "latest_url": latest_url,
                "dry_run": False,
                "poll_interval": 0.02,
                "speed_percent": 60,
                "pan_joint": "j11",
                "tilt_joint": "j13",
                "pan_dead_zone_norm": 0.07,
                "tilt_dead_zone_norm": 0.08,
                "pan_resume_zone_norm": 0.11,
                "tilt_resume_zone_norm": 0.12,
                "min_pan_step_deg": 0.1,
                "min_tilt_step_deg": 0.2,
                "pan_min_step_zone_norm": 0.31,
                "tilt_min_step_zone_norm": 0.32,
                "rail_enabled": True,
                "rail_start_mm": -140,
                "rail_end_mm": 140,
                "rail_speed_mm_s": 30.0,
            },
        )
        assert started["ok"] is True, started
        time.sleep(0.25)
        status = get_json("/api/v1/follow/status")
        assert status["ok"] is True, status
        follow = status["data"]
        assert follow.get("dry_run") is True, "视觉跟随模式应跟随全局 dry_run 会话，而不是请求体 dry_run 字段"
        effective = follow.get("effective_config") or {}
        assert effective.get("pan_dead_zone_norm") == 0.07, effective
        assert effective.get("tilt_dead_zone_norm") == 0.08, effective
        assert effective.get("pan_resume_zone_norm") == 0.11, effective
        assert effective.get("tilt_resume_zone_norm") == 0.12, effective
        assert effective.get("min_pan_step_deg") == 0.1, effective
        assert effective.get("min_tilt_step_deg") == 0.2, effective
        assert effective.get("pan_min_step_zone_norm") == 0.31, effective
        assert effective.get("tilt_min_step_zone_norm") == 0.32, effective
        commands = (follow.get("last_command") or {}).get("commands") or []
        joints = {item["joint_key"] for item in commands}
        assert "j10" in joints, f"导轨运镜应包含 J10 命令，实际：{commands}"
        assert {"j11", "j13"}.issubset(joints), f"人脸跟随应保留 J11/J13，实际：{commands}"
        print("Web dry-run 视觉导轨跟随测试通过")
        print(json.dumps({"commands": commands, "rail": follow.get("rail")}, ensure_ascii=False, indent=2))
    finally:
        try:
            post_json("/api/v1/follow/stop")
        except Exception:
            pass
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
