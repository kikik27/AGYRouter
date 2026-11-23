from typing import Any, Dict, Optional
from fastapi import Header, HTTPException, Request

from app.config import API_KEY as ENV_API_KEY
from app.database import get_setting, validate_api_key, verify_session_token

COOKIE_NAME = "agy_session"


def extract_admin_token(request: Request) -> Optional[str]:
    """Extract admin session token from HttpOnly cookie or X-Admin-Token header."""
    cookie_tok = request.cookies.get(COOKIE_NAME)
    if cookie_tok:
        return cookie_tok
    header_tok = request.headers.get("x-admin-token")
    if header_tok:
        return header_tok.strip()
    return None


def require_admin(request: Request) -> bool:
    """FastAPI dependency that ensures a valid admin session token is present."""
    token = extract_admin_token(request)
    if not verify_session_token(token):
        raise HTTPException(status_code=401, detail="Authentication required")
    return True


def verify_proxy_api_key(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    FastAPI dependency for /v1/* and /api/chat endpoints.
    Supports Authorization: Bearer <key> and x-api-key: <key>.
    """
    raw_token = ""
    if authorization:
        if authorization.lower().startswith("bearer "):
            raw_token = authorization[7:].strip()
        else:
            raw_token = authorization.strip()
    elif x_api_key:
        raw_token = x_api_key.strip()

    require_key = get_setting("require_api_key", "1") == "1"

    if raw_token:
        # 1. Check against active DB API keys
        key_record = validate_api_key(raw_token)
        if key_record:
            return key_record

        # 2. Fallback check against optional .env master API_KEY
        if ENV_API_KEY and raw_token == ENV_API_KEY:
            return {
                "id": "env-master",
                "name": "Env Master Key",
                "allowed_model": "*",
            }

        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Invalid or disabled API key.",
                    "type": "authentication_error",
                    "code": "invalid_api_key",
                }
            },
        )

    if require_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Missing API key. Pass Authorization: Bearer sk-agy-... or x-api-key header.",
                    "type": "authentication_error",
                    "code": "missing_api_key",
                }
            },
        )

    return {
        "id": "anonymous",
        "name": "Anonymous",
        "allowed_model": "*",
    }
