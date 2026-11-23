import asyncio
import os
import shutil
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.agy_connector import AsyncAGYConnector
from app.auth import COOKIE_NAME, extract_admin_token, require_admin
from app.config import (
    AGY_BIN_PATH,
    AGY_SUPPORTED_MODELS,
    DEFAULT_MODEL,
    HOST,
    PORT,
    get_local_lan_ip,
)
from app.database import (
    clear_request_logs,
    create_api_key,
    create_session_token,
    delete_api_key,
    delete_model_route,
    get_analytics_summary,
    get_setting,
    hash_password,
    list_api_keys,
    list_model_routes,
    list_request_logs,
    set_setting,
    update_api_key,
    upsert_model_route,
    verify_password,
    verify_session_token,
)
from app.service_manager import (
    detect_device,
    get_service_status,
    install_service,
    uninstall_service,
)
from app.tunnel import tunnel_manager

router = APIRouter(tags=["Admin & Auth"])


# --- Request Schemas ---

class LoginPayload(BaseModel):
    password: str


class ChangePasswordPayload(BaseModel):
    current_password: str
    new_password: str = Field(min_length=4)


class CreateKeyPayload(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    allowed_model: str = "*"


class UpdateKeyPayload(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    allowed_model: Optional[str] = None


class RoutePayload(BaseModel):
    alias: str = Field(min_length=1, max_length=100)
    target_model: str = Field(min_length=1, max_length=100)
    description: str = ""


class TestModelPayload(BaseModel):
    model: str = DEFAULT_MODEL


class SettingsPayload(BaseModel):
    default_model: Optional[str] = None
    require_api_key: Optional[bool] = None
    allow_tool_execution: Optional[bool] = None


class TunnelStartPayload(BaseModel):
    mode: str = "quick"
    protocol: Optional[str] = "http2"
    token: Optional[str] = None
    custom_url: Optional[str] = None
    autostart: Optional[bool] = None
    auto_install: bool = True


class TunnelConfigPayload(BaseModel):
    autostart: Optional[bool] = None
    mode: Optional[str] = None
    protocol: Optional[str] = None
    token: Optional[str] = None
    custom_url: Optional[str] = None


class ServiceInstallPayload(BaseModel):
    enable_tunnel: bool = False


# --- Authentication Endpoints ---

@router.get("/api/auth/status")
async def auth_status(request: Request):
    """Check whether the client holds a valid admin session cookie or X-Admin-Token."""
    token = extract_admin_token(request)
    return {
        "authenticated": verify_session_token(token),
        "is_default_password": get_setting("is_default_password", "1") == "1",
    }


@router.post("/api/auth/login")
async def auth_login(payload: LoginPayload, response: Response):
    """Verify dashboard password and issue a 30-day HttpOnly cookie + token."""
    stored_hash = get_setting("password_hash")
    if not verify_password(payload.password, stored_hash):
        raise HTTPException(status_code=401, detail="Password salah. Silakan coba lagi.")

    token = create_session_token(ttl_seconds=30 * 86400)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=30 * 86400,
    )
    return {
        "authenticated": True,
        "session_token": token,
        "is_default_password": get_setting("is_default_password", "1") == "1",
    }


@router.post("/api/auth/logout")
async def auth_logout(response: Response):
    """Clear session cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"authenticated": False}


@router.post("/api/auth/change-password")
async def auth_change_password(
    payload: ChangePasswordPayload,
    _: bool = Depends(require_admin),
):
    """Change the admin dashboard password."""
    stored_hash = get_setting("password_hash")
    if not verify_password(payload.current_password, stored_hash):
        raise HTTPException(status_code=400, detail="Password saat ini tidak cocok.")

    set_setting("password_hash", hash_password(payload.new_password))
    set_setting("is_default_password", "0")
    return {"ok": True, "is_default_password": False}


# --- Protected Admin Endpoints ---

@router.get("/api/admin/overview")
async def admin_overview(_: bool = Depends(require_admin)):
    """Aggregate KPIs, 24h traffic, model breakdown, and gateway metadata."""
    summary = get_analytics_summary()
    keys = list_api_keys()
    active_keys = [k for k in keys if k["is_active"]]
    bin_exists = os.path.exists(AGY_BIN_PATH) if AGY_BIN_PATH else False
    in_path = shutil.which("agy") is not None

    return {
        **summary,
        "server": {
            "host": HOST,
            "port": PORT,
            "lan_ip": get_local_lan_ip(),
            "agy_binary": AGY_BIN_PATH,
            "binary_found": bin_exists or in_path,
            "default_model": get_setting("default_model", DEFAULT_MODEL),
            "require_api_key": get_setting("require_api_key", "1") == "1",
            "allow_tool_execution": get_setting("allow_tool_execution", "0") == "1",
            "active_keys_count": len(active_keys),
            "total_keys_count": len(keys),
            "default_key_value": active_keys[0]["key_value"] if active_keys else "",
            "tunnel_running": tunnel_manager.is_running(),
            "tunnel_url": tunnel_manager.public_url,
        },
    }


@router.get("/api/admin/keys")
async def admin_list_keys(_: bool = Depends(require_admin)):
    return {
        "keys": list_api_keys(),
        "require_api_key": get_setting("require_api_key", "1") == "1",
    }


@router.post("/api/admin/keys")
async def admin_create_key(
    payload: CreateKeyPayload,
    _: bool = Depends(require_admin),
):
    key = create_api_key(name=payload.name, allowed_model=payload.allowed_model)
    return {"key": key}


@router.patch("/api/admin/keys/{key_id}")
async def admin_update_key(
    key_id: str,
    payload: UpdateKeyPayload,
    _: bool = Depends(require_admin),
):
    updated = update_api_key(
        key_id=key_id,
        name=payload.name,
        is_active=payload.is_active,
        allowed_model=payload.allowed_model,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"key": updated}


@router.delete("/api/admin/keys/{key_id}")
async def admin_delete_key(key_id: str, _: bool = Depends(require_admin)):
    deleted = delete_api_key(key_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"ok": True}


@router.get("/api/admin/routes")
async def admin_list_routes(_: bool = Depends(require_admin)):
    return {
        "routes": list_model_routes(),
        "supported_models": AGY_SUPPORTED_MODELS,
    }


@router.post("/api/admin/routes")
async def admin_upsert_route(
    payload: RoutePayload,
    _: bool = Depends(require_admin),
):
    route = upsert_model_route(
        alias=payload.alias,
        target_model=payload.target_model,
        description=payload.description,
    )
    return {"route": route}


@router.delete("/api/admin/routes/{alias:path}")
async def admin_delete_route(alias: str, _: bool = Depends(require_admin)):
    deleted = delete_model_route(alias)
    if not deleted:
        raise HTTPException(status_code=404, detail="Route alias not found")
    return {"ok": True}


@router.post("/api/admin/models/refresh")
async def admin_refresh_models(_: bool = Depends(require_admin)):
    models = await AsyncAGYConnector.list_live_models()
    return {"models": models}


@router.post("/api/admin/models/test")
async def admin_test_model(
    payload: TestModelPayload,
    _: bool = Depends(require_admin),
):
    try:
        return await AsyncAGYConnector.ping_model(payload.model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model test failed: {str(e)}")


@router.get("/api/admin/logs")
async def admin_list_logs(
    limit: int = 100,
    api_key_id: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
    _: bool = Depends(require_admin),
):
    logs = list_request_logs(
        limit=limit,
        api_key_id=api_key_id or None,
        model=model or None,
        status=status or None,
    )
    return {"logs": logs}


@router.delete("/api/admin/logs")
async def admin_clear_logs(_: bool = Depends(require_admin)):
    clear_request_logs()
    return {"ok": True}


@router.get("/api/admin/settings")
async def admin_get_settings(_: bool = Depends(require_admin)):
    return {
        "default_model": get_setting("default_model", DEFAULT_MODEL),
        "require_api_key": get_setting("require_api_key", "1") == "1",
        "allow_tool_execution": get_setting("allow_tool_execution", "0") == "1",
        "is_default_password": get_setting("is_default_password", "1") == "1",
        "supported_models": AGY_SUPPORTED_MODELS,
        "agy_binary": AGY_BIN_PATH,
        "host": HOST,
        "port": PORT,
        "lan_ip": get_local_lan_ip(),
    }


@router.patch("/api/admin/settings")
async def admin_update_settings(
    payload: SettingsPayload,
    _: bool = Depends(require_admin),
):
    if payload.default_model is not None:
        set_setting("default_model", payload.default_model.strip())
    if payload.require_api_key is not None:
        set_setting("require_api_key", "1" if payload.require_api_key else "0")
    if payload.allow_tool_execution is not None:
        set_setting("allow_tool_execution", "1" if payload.allow_tool_execution else "0")

    return {
        "default_model": get_setting("default_model", DEFAULT_MODEL),
        "require_api_key": get_setting("require_api_key", "1") == "1",
        "allow_tool_execution": get_setting("allow_tool_execution", "0") == "1",
    }


# --- Cloudflare Tunnel Management ---

@router.get("/api/admin/tunnel")
async def admin_tunnel_status(_: bool = Depends(require_admin)):
    return tunnel_manager.get_status()


@router.post("/api/admin/tunnel/install")
async def admin_tunnel_install(_: bool = Depends(require_admin)):
    try:
        await tunnel_manager.install_binary()
        return tunnel_manager.get_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal install cloudflared: {str(e)}")


@router.post("/api/admin/tunnel/start")
async def admin_tunnel_start(
    payload: TunnelStartPayload,
    _: bool = Depends(require_admin),
):
    clean_mode = "token" if payload.mode == "token" else "quick"
    clean_proto = payload.protocol if payload.protocol in ("http2", "auto", "quic") else get_setting("tunnel_protocol", "http2")
    set_setting("tunnel_mode", clean_mode)
    set_setting("tunnel_protocol", clean_proto)
    if payload.custom_url is not None:
        set_setting("tunnel_custom_url", payload.custom_url.strip())
    if payload.autostart is not None:
        set_setting("tunnel_autostart", "1" if payload.autostart else "0")

    effective_token = (payload.token or "").strip()
    if effective_token:
        set_setting("tunnel_token", effective_token)
    elif clean_mode == "token":
        effective_token = get_setting("tunnel_token", "")

    effective_custom_url = payload.custom_url if payload.custom_url is not None else get_setting("tunnel_custom_url", "")

    try:
        return await tunnel_manager.start(
            mode=clean_mode,
            token=effective_token,
            custom_url=effective_custom_url,
            port=PORT,
            protocol=clean_proto,
            auto_install=payload.auto_install,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal menjalankan tunnel: {str(e)}")


@router.post("/api/admin/tunnel/stop")
async def admin_tunnel_stop(_: bool = Depends(require_admin)):
    return await tunnel_manager.stop()


@router.patch("/api/admin/tunnel/config")
async def admin_tunnel_config(
    payload: TunnelConfigPayload,
    _: bool = Depends(require_admin),
):
    if payload.autostart is not None:
        set_setting("tunnel_autostart", "1" if payload.autostart else "0")
    if payload.mode is not None:
        set_setting("tunnel_mode", "token" if payload.mode == "token" else "quick")
    if payload.protocol in ("http2", "auto", "quic"):
        set_setting("tunnel_protocol", payload.protocol)
    if payload.token is not None:
        set_setting("tunnel_token", payload.token.strip())
    if payload.custom_url is not None:
        set_setting("tunnel_custom_url", payload.custom_url.strip())
    return tunnel_manager.get_status()


# --- Device Auto-Detection & Native 24/7 Service ---

@router.get("/api/admin/device")
async def admin_device_info(_: bool = Depends(require_admin)):
    return detect_device()


@router.get("/api/admin/service")
async def admin_service_status(_: bool = Depends(require_admin)):
    return {
        "device": detect_device(),
        "service": get_service_status(),
    }


@router.post("/api/admin/service/install")
async def admin_service_install(
    payload: ServiceInstallPayload,
    _: bool = Depends(require_admin),
):
    try:
        service = await asyncio.to_thread(install_service, payload.enable_tunnel)
        return {
            "device": detect_device(),
            "service": service,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal install service: {str(e)}")


@router.post("/api/admin/service/uninstall")
async def admin_service_uninstall(_: bool = Depends(require_admin)):
    try:
        service = await asyncio.to_thread(uninstall_service)
        return {
            "device": detect_device(),
            "service": service,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal uninstall service: {str(e)}")
