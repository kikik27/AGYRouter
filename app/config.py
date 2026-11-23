import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Base & Data Directories
BASE_DIR: Path = Path(__file__).parent.parent
DATA_DIR: Path = BASE_DIR / "data"

# Server Settings
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))
API_KEY: str = os.getenv("API_KEY", "").strip()
DASHBOARD_PASSWORD: str = os.getenv("DASHBOARD_PASSWORD", "123456")

# AGY Default Model
DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "gemini-3.8-flash-high")


def _detect_agy_binary() -> str:
    """Detect official Antigravity CLI binary across Windows, Linux, and macOS."""
    in_path = shutil.which("agy")
    if in_path:
        return in_path

    if sys.platform == "win32":
        win_candidate = Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.EXE"
        if win_candidate.exists():
            return str(win_candidate)
        return str(win_candidate)

    posix_candidate = Path.home() / ".local" / "bin" / "agy"
    if posix_candidate.exists():
        return str(posix_candidate)
    return "agy"


detected_path = _detect_agy_binary()
AGY_BIN_PATH: str = os.getenv("AGY_PATH", "").strip() or detected_path

# Allow Tool Execution in AGY (default False for pure LLM safety)
ALLOW_TOOL_EXECUTION: bool = os.getenv("ALLOW_TOOL_EXECUTION", "false").lower() in ("true", "1", "yes")

# Concurrency & Timeout Limits
MAX_CONCURRENT_REQUESTS: int = int(os.getenv("MAX_CONCURRENT_REQUESTS", "4"))
AGY_TIMEOUT_SECONDS: int = int(os.getenv("AGY_TIMEOUT_SECONDS", "180"))

# Supported native AGY models
AGY_SUPPORTED_MODELS = [
    "gemini-3.8-flash-high",
    "gemini-3.8-flash-medium",
    "gemini-3.8-flash-low",
    "gemini-4-neon-high",
    "gemini-4-neon-xhigh",
    "gemini-4-neon-medium",
    "gemini-4-neon-low",
    "gemini-4-argon-high",
    "gemini-4-argon-medium",
    "gemini-4-argon-low",
    "gemini-4-hydrogen-high",
    "gemini-4-hydrogen-xhigh",
    "gemini-4-hydrogen-medium",
    "gemini-4-hydrogen-low",
    "claude-sonnet-5-5-high",
    "claude-sonnet-5-5-medium",
    "claude-sonnet-5-5-low",
    "claude-opus-5-5-high",
    "claude-opus-5-5-medium",
    "claude-opus-5-5-low",
    "gpt-oss-120b-medium",
]

# Model Alias Mapping for seamless Agentic Frameworks compatibility
MODEL_ALIASES = {
    # OpenAI Aliases
    "gpt-4": "gemini-4-neon-high",
    "gpt-4o": "gemini-4-neon-high",
    "gpt-4o-mini": "gemini-3.8-flash-high",
    "gpt-3.5-turbo": "gemini-3.8-flash-medium",
    "o1": "gemini-4-neon-xhigh",
    "o3-mini": "gemini-3.8-flash-high",

    # Anthropic Aliases
    "claude-3-5-sonnet": "claude-sonnet-5-5-high",
    "claude-3-5-sonnet-20241022": "claude-sonnet-5-5-high",
    "claude-3-opus": "claude-opus-5-5-high",
    "claude-3-opus-20240229": "claude-opus-5-5-high",
    "claude-3-haiku": "gemini-3.8-flash-high",

    # Gemini Aliases
    "gemini-1.5-pro": "gemini-4-neon-high",
    "gemini-1.5-flash": "gemini-3.8-flash-high",
    "gemini-2.0-flash": "gemini-3.8-flash-high",
    "gemini-pro": "gemini-3.8-flash-high",
}


def resolve_model(
    requested_model: str,
    custom_routes: Optional[Dict[str, str]] = None,
    fallback_model: Optional[str] = None,
) -> str:
    """Resolve requested model name or alias to official AGY model."""
    fallback = fallback_model or DEFAULT_MODEL
    if not requested_model:
        return fallback

    cleaned = requested_model.strip().lower()

    # 1. Check custom routing aliases from database first
    if custom_routes:
        for alias, target in custom_routes.items():
            if alias.strip().lower() == cleaned:
                return target

    # 2. Check built-in aliases
    if cleaned in MODEL_ALIASES:
        return MODEL_ALIASES[cleaned]

    # 3. Exact match in supported AGY models
    for model in AGY_SUPPORTED_MODELS:
        if model.lower() == cleaned:
            return model

    # 4. Substring search match
    for model in AGY_SUPPORTED_MODELS:
        if cleaned in model.lower():
            return model

    return fallback


def get_local_lan_ip() -> str:
    """Detect local LAN IP address safely without blocking."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(0.2)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        return ip or "127.0.0.1"
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()
