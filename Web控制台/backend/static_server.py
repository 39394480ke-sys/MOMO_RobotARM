"""前端静态文件同源部署。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def install_static_routes(app: FastAPI, base_dir: str | Path) -> None:
    """挂载 /static，并让 / 和 /web/ 都返回控制台首页。"""

    root = Path(base_dir).resolve()
    frontend_dir = root / "frontend"
    index_path = frontend_dir / "index.html"

    app.mount("/static", StaticFiles(directory=frontend_dir), name="web_static")

    @app.get("/", include_in_schema=False)
    async def index_root() -> FileResponse:
        return FileResponse(index_path)

    @app.get("/web", include_in_schema=False)
    async def index_web_no_slash() -> FileResponse:
        return FileResponse(index_path)

    @app.get("/web/", include_in_schema=False)
    async def index_web() -> FileResponse:
        return FileResponse(index_path)
