"""启动阶段八 API 服务。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


WEB_DIR = Path(__file__).resolve().parents[1]
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 Web API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()

    try:
        import uvicorn

        from backend.app import app
    except ImportError as exc:
        print("缺少依赖，请先执行：pip install fastapi uvicorn pydantic pyyaml")
        print(f"原始错误：{exc}")
        raise SystemExit(1) from exc

    print(f"API 已启动：http://{args.host}:{args.port}/web/")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
