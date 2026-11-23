import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import PORT
from app.database import get_setting, init_db
from app.routes.admin_routes import router as admin_router
from app.routes.native_routes import router as native_router
from app.routes.openai_routes import router as openai_router
from app.tunnel import tunnel_manager

logger = logging.getLogger("agy_main")

# Ensure SQLite schema and initial admin/API key defaults exist on startup & test import
init_db()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if os.getenv("AGY_DISABLE_AUTOSTART") != "1" and get_setting("tunnel_autostart", "0") == "1":
        mode = get_setting("tunnel_mode", "quick")
        token = get_setting("tunnel_token", "")
        custom_url = get_setting("tunnel_custom_url", "")
        try:
            await tunnel_manager.start(mode=mode, token=token, custom_url=custom_url, port=PORT)
        except Exception as e:
            logger.warning(f"Tunnel auto-start skipped: {e}")
    yield
    await tunnel_manager.stop()


# Initialize FastAPI App
app = FastAPI(
    title="AGYRouter — Official Local AI Gateway",
    description="Official, ToS-compliant local OpenAI-compatible AI gateway and router for Google Antigravity (agy CLI).",
    version="2.0.0",
    lifespan=lifespan,
)

# Enable CORS for cross-origin integration (Cursor, web dashboards, remote clients)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(admin_router)
app.include_router(openai_router)
app.include_router(native_router)

# Mount Static Files and Web Dashboard
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_dashboard():
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {"message": "AGY Router API is running. Visit /docs for OpenAPI documentation."}
