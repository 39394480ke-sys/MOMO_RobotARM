"""启动阶段八 Web 控制台。"""

from __future__ import annotations

import argparse

from backend.path_utils import ensure_project_root_on_path

ensure_project_root_on_path()


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 机械臂 Web 控制台")
    parser.add_argument("--host", default=None, help="监听地址，默认读取 Web配置.yaml")
    parser.add_argument("--port", type=int, default=None, help="监听端口，默认读取 Web配置.yaml")
    args = parser.parse_args()

    try:
        import uvicorn

        from backend.app import CONFIG, app
    except ImportError as exc:
        print("启动失败：缺少 Web 后端依赖。")
        print("请先执行：pip install fastapi uvicorn pydantic pyyaml")
        print(f"原始错误：{exc}")
        raise SystemExit(1) from exc

    server_cfg = CONFIG.get("server", {})
    app_cfg = CONFIG.get("app", {})
    host = args.host or str(server_cfg.get("host", "127.0.0.1"))
    port = int(args.port or server_cfg.get("port", 8010))
    reload = bool(server_cfg.get("reload", False))
    shown_host = "127.0.0.1" if host == "0.0.0.0" else host

    print("Web 控制台已启动：")
    print(f"http://{shown_host}:{port}/web/")
    print("")
    print(f"当前默认模式：{app_cfg.get('default_mode', 'dry_run')}")
    print("真实硬件不会自动连接。")

    uvicorn.run(app, host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
