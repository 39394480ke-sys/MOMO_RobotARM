"""WebSocket 状态推送测试。

需要：
    pip install websockets
"""

from __future__ import annotations

import asyncio
import json

from Web测试客户端_test_client import web_ws_url


async def main_async() -> None:
    try:
        import websockets
    except ImportError as exc:
        print("缺少 websockets，请先执行：pip install websockets")
        raise SystemExit(1) from exc

    messages = []
    async with websockets.connect(web_ws_url(), open_timeout=5) as websocket:
        for _ in range(3):
            raw = await asyncio.wait_for(websocket.recv(), timeout=3)
            msg = json.loads(raw)
            messages.append(msg)
            print(json.dumps(msg, ensure_ascii=False, indent=2))
    assert len(messages) >= 3
    assert all(msg.get("type") in {"state", "error"} for msg in messages)
    print("websocket state ok")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
