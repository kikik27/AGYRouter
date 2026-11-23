import os
import shutil
import time
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.agy_connector import AsyncAGYConnector
from app.auth import verify_proxy_api_key
from app.config import AGY_BIN_PATH, AGY_SUPPORTED_MODELS, DEFAULT_MODEL
from app.database import get_setting, insert_request_log, record_key_usage
from app.schemas import NativeChatRequest, NativeChatResponse

router = APIRouter(tags=["Native AGY"])


@router.get("/health")
@router.get("/api/status")
async def health_check():
    """Public health and status check for AGY CLI connection."""
    bin_exists = os.path.exists(AGY_BIN_PATH) if AGY_BIN_PATH else False
    in_path = shutil.which("agy") is not None

    return {
        "status": "healthy" if (bin_exists or in_path) else "warning",
        "proxy_version": "2.0.0",
        "binary_found": bin_exists or in_path,
    }


@router.get("/api/models")
async def get_native_models(_: Dict[str, Any] = Depends(verify_proxy_api_key)):
    """List native AGY models."""
    return {
        "default": get_setting("default_model", DEFAULT_MODEL),
        "models": AGY_SUPPORTED_MODELS,
    }


@router.post("/api/chat")
async def native_chat(
    req: NativeChatRequest,
    key_info: Dict[str, Any] = Depends(verify_proxy_api_key),
):
    """Native AGY chat endpoint."""
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    requested_model = req.model or ""
    allowed_model = key_info.get("allowed_model", "*")
    effective_model = allowed_model if allowed_model not in (None, "", "*") else requested_model
    resolved_model = AsyncAGYConnector.resolve_effective_model(effective_model)
    start_ts = time.perf_counter()

    if req.stream:
        async def event_generator():
            final_conv_id = req.conversation_id
            final_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            status_code = 200
            error_msg = None
            try:
                async for ev in AsyncAGYConnector.stream_execution(
                    prompt=req.prompt,
                    model=resolved_model,
                    conversation_id=req.conversation_id,
                    effort=req.effort,
                ):
                    if ev.get("type") == "init":
                        final_conv_id = ev.get("conversation_id")
                    elif ev.get("type") == "delta":
                        yield ev.get("content", "")
                    elif ev.get("type") == "result":
                        final_conv_id = ev.get("conversation_id", final_conv_id)
                        final_usage = ev.get("usage", final_usage)
            except Exception as e:
                status_code = 500
                error_msg = str(e)
                yield f"\n[Error]: {error_msg}"
            finally:
                latency_ms = int((time.perf_counter() - start_ts) * 1000)
                total_tok = int(final_usage.get("total_tokens", 0) or 0)
                insert_request_log(
                    endpoint="/api/chat",
                    requested_model=requested_model or resolved_model,
                    resolved_model=resolved_model,
                    stream=True,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    prompt_tokens=final_usage.get("prompt_tokens", 0),
                    completion_tokens=final_usage.get("completion_tokens", 0),
                    total_tokens=total_tok,
                    api_key_id=key_info.get("id"),
                    api_key_name=key_info.get("name"),
                    conversation_id=final_conv_id,
                    prompt_preview=req.prompt,
                    error_message=error_msg,
                )
                if status_code < 400:
                    record_key_usage(key_info.get("id"), total_tok)

        return StreamingResponse(event_generator(), media_type="text/plain")

    try:
        result = await AsyncAGYConnector.run_single(
            prompt=req.prompt,
            model=resolved_model,
            conversation_id=req.conversation_id,
            effort=req.effort,
        )
        latency_ms = int((time.perf_counter() - start_ts) * 1000)
        usage = result.get("usage", {})
        total_tok = int(usage.get("total_tokens", 0) or 0)
        insert_request_log(
            endpoint="/api/chat",
            requested_model=requested_model or resolved_model,
            resolved_model=resolved_model,
            stream=False,
            status_code=200,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=total_tok,
            api_key_id=key_info.get("id"),
            api_key_name=key_info.get("name"),
            conversation_id=result.get("conversation_id"),
            prompt_preview=req.prompt,
        )
        record_key_usage(key_info.get("id"), total_tok)

        return NativeChatResponse(
            response=result.get("response", ""),
            conversation_id=result.get("conversation_id", ""),
            model=resolved_model,
            duration_seconds=result.get("duration_seconds", 0.0),
            usage=usage,
            status="SUCCESS",
        )
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_ts) * 1000)
        insert_request_log(
            endpoint="/api/chat",
            requested_model=requested_model or resolved_model,
            resolved_model=resolved_model,
            stream=False,
            status_code=500,
            latency_ms=latency_ms,
            api_key_id=key_info.get("id"),
            api_key_name=key_info.get("name"),
            prompt_preview=req.prompt,
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))
