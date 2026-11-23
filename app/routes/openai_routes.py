import json
import time
import uuid
from typing import Any, AsyncGenerator, Dict
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.agy_connector import AsyncAGYConnector, format_messages_to_prompt
from app.auth import verify_proxy_api_key
from app.config import AGY_SUPPORTED_MODELS
from app.database import (
    get_model_routes_map,
    insert_request_log,
    record_key_usage,
)
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionResponseChoice,
    ChatCompletionUsage,
    ChatMessage,
    ModelCard,
    ModelListResponse,
)

router = APIRouter(prefix="/v1", tags=["OpenAI Compatible"])


@router.get("/models", response_model=ModelListResponse)
async def list_models(_: Dict[str, Any] = Depends(verify_proxy_api_key)):
    """Return all native AGY models and configured routing aliases."""
    seen = set()
    model_cards = []
    for m in AGY_SUPPORTED_MODELS:
        if m not in seen:
            seen.add(m)
            model_cards.append(ModelCard(id=m))

    routes_map = get_model_routes_map()
    for alias in routes_map.keys():
        if alias not in seen:
            seen.add(alias)
            model_cards.append(ModelCard(id=alias))

    return ModelListResponse(data=model_cards)


@router.get("/models/{model_id}", response_model=ModelCard)
async def get_model(model_id: str, _: Dict[str, Any] = Depends(verify_proxy_api_key)):
    """Retrieve a single model card by ID or alias."""
    routes_map = get_model_routes_map()
    if model_id in AGY_SUPPORTED_MODELS or model_id in routes_map:
        return ModelCard(id=model_id)
    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")


@router.post("/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    key_info: Dict[str, Any] = Depends(verify_proxy_api_key),
):
    """
    OpenAI-compatible Chat Completions endpoint.
    Supports both streaming (text/event-stream SSE) and standard JSON.
    """
    if not request.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty")

    requested_model = request.model or ""
    allowed_model = key_info.get("allowed_model", "*")
    effective_request_model = allowed_model if allowed_model not in (None, "", "*") else requested_model
    resolved_model = AsyncAGYConnector.resolve_effective_model(effective_request_model)

    session_key = request.user or request.conversation_id
    mapped_conv_id = AsyncAGYConnector.get_mapped_conversation_id(
        session_key=session_key,
        explicit_conv_id=request.conversation_id,
    )
    prompt = format_messages_to_prompt(request.messages, is_continuation=bool(mapped_conv_id))

    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created_time = int(time.time())
    start_ts = time.perf_counter()

    # --- Streaming Response (SSE) ---
    if request.stream:
        async def sse_event_stream() -> AsyncGenerator[str, None]:
            final_conv_id = mapped_conv_id
            final_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            status_code = 200
            error_msg = None

            initial_chunk = {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": resolved_model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(initial_chunk)}\n\n"

            try:
                async for event in AsyncAGYConnector.stream_execution(
                    prompt=prompt,
                    model=resolved_model,
                    conversation_id=mapped_conv_id,
                    effort=request.effort,
                ):
                    event_type = event.get("type")
                    if event_type == "init":
                        final_conv_id = event.get("conversation_id")
                    elif event_type == "delta":
                        text = event.get("content", "")
                        if text:
                            chunk = {
                                "id": request_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": resolved_model,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": text},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(chunk)}\n\n"
                    elif event_type == "result":
                        final_conv_id = event.get("conversation_id", final_conv_id)
                        final_usage = event.get("usage", final_usage)

                final_chunk = {
                    "id": request_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": resolved_model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": final_usage,
                }
                yield f"data: {json.dumps(final_chunk)}\n\n"
                yield "data: [DONE]\n\n"

                if session_key and final_conv_id:
                    AsyncAGYConnector.save_conversation_mapping(session_key, final_conv_id)

            except Exception as e:
                status_code = 500
                error_msg = str(e)
                error_chunk = {
                    "id": request_id,
                    "error": {"message": error_msg, "type": "server_error"},
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                latency_ms = int((time.perf_counter() - start_ts) * 1000)
                total_tok = int(final_usage.get("total_tokens", 0) or 0)
                insert_request_log(
                    endpoint="/v1/chat/completions",
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
                    prompt_preview=prompt,
                    error_message=error_msg,
                )
                if status_code < 400:
                    record_key_usage(key_info.get("id"), total_tok)

        return StreamingResponse(
            sse_event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # --- Non-Streaming Response ---
    try:
        result = await AsyncAGYConnector.run_single(
            prompt=prompt,
            model=resolved_model,
            conversation_id=mapped_conv_id,
            effort=request.effort,
        )

        final_conv_id = result.get("conversation_id")
        if session_key and final_conv_id:
            AsyncAGYConnector.save_conversation_mapping(session_key, final_conv_id)

        usage_data = result.get("usage", {})
        usage = ChatCompletionUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )
        latency_ms = int((time.perf_counter() - start_ts) * 1000)

        insert_request_log(
            endpoint="/v1/chat/completions",
            requested_model=requested_model or resolved_model,
            resolved_model=resolved_model,
            stream=False,
            status_code=200,
            latency_ms=latency_ms,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            api_key_id=key_info.get("id"),
            api_key_name=key_info.get("name"),
            conversation_id=final_conv_id,
            prompt_preview=prompt,
        )
        record_key_usage(key_info.get("id"), usage.total_tokens)

        return ChatCompletionResponse(
            id=request_id,
            created=created_time,
            model=resolved_model,
            choices=[
                ChatCompletionResponseChoice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=result.get("response", ""),
                    ),
                    finish_reason="stop",
                )
            ],
            usage=usage,
            conversation_id=final_conv_id,
        )

    except Exception as e:
        latency_ms = int((time.perf_counter() - start_ts) * 1000)
        insert_request_log(
            endpoint="/v1/chat/completions",
            requested_model=requested_model or resolved_model,
            resolved_model=resolved_model,
            stream=False,
            status_code=500,
            latency_ms=latency_ms,
            api_key_id=key_info.get("id"),
            api_key_name=key_info.get("name"),
            prompt_preview=prompt,
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=f"AGY execution failed: {str(e)}")
