import asyncio
import json
import logging
import time
import uuid
from typing import AsyncGenerator, Dict, Any, Optional, List
from app.config import (
    AGY_BIN_PATH,
    AGY_SUPPORTED_MODELS,
    AGY_TIMEOUT_SECONDS,
    DEFAULT_MODEL,
    MAX_CONCURRENT_REQUESTS,
    resolve_model,
)
from app.database import (
    get_model_routes_map,
    get_session_conversation,
    get_setting,
    save_session_conversation,
)
from app.schemas import ChatMessage

logger = logging.getLogger("agy_connector")
logging.basicConfig(level=logging.INFO)


def format_messages_to_prompt(messages: List[ChatMessage], is_continuation: bool = False) -> str:
    """
    Format messages array into a well-structured prompt for AGY CLI.
    When is_continuation=True and prior assistant turns exist, only send the new
    turn(s) after the last assistant message to avoid duplicating context tokens.
    """
    if not messages:
        return ""

    effective_messages = messages
    if is_continuation:
        last_assistant_idx = -1
        for idx, msg in enumerate(messages):
            if msg.role.lower() == "assistant":
                last_assistant_idx = idx
        if 0 <= last_assistant_idx < len(messages) - 1:
            effective_messages = messages[last_assistant_idx + 1 :]

    if len(effective_messages) == 1 and effective_messages[0].role.lower() == "user":
        return effective_messages[0].get_text_content().strip()

    prompt_parts: List[str] = []
    system_parts: List[str] = []

    for msg in effective_messages:
        role = msg.role.lower()
        content = msg.get_text_content().strip()
        if not content:
            continue

        if role == "system":
            system_parts.append(content)
        elif role == "user":
            prompt_parts.append(f"User: {content}")
        elif role == "assistant":
            prompt_parts.append(f"Assistant: {content}")
        else:
            prompt_parts.append(f"[{role.capitalize()}]: {content}")

    formatted_str = ""
    if system_parts:
        formatted_str += "[System Instruction]\n" + "\n\n".join(system_parts) + "\n\n"

    formatted_str += "\n\n".join(prompt_parts)
    return formatted_str.strip()


class AsyncAGYConnector:
    """Handles official, ToS-compliant execution of agy CLI subprocess."""

    _semaphore: Optional[asyncio.Semaphore] = None
    _semaphore_loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if cls._semaphore is None or cls._semaphore_loop is not loop:
            cls._semaphore = asyncio.Semaphore(max(1, MAX_CONCURRENT_REQUESTS))
            cls._semaphore_loop = loop
        return cls._semaphore

    @staticmethod
    def get_mapped_conversation_id(session_key: Optional[str], explicit_conv_id: Optional[str]) -> Optional[str]:
        if explicit_conv_id:
            return explicit_conv_id
        if session_key:
            return get_session_conversation(session_key)
        return None

    @staticmethod
    def save_conversation_mapping(session_key: Optional[str], conv_id: Optional[str], model: str = "") -> None:
        if session_key and conv_id:
            save_session_conversation(session_key, conv_id, model=model)

    @staticmethod
    def resolve_effective_model(requested_model: Optional[str]) -> str:
        custom_routes = get_model_routes_map()
        fallback = get_setting("default_model", DEFAULT_MODEL)
        return resolve_model(requested_model or "", custom_routes=custom_routes, fallback_model=fallback)

    @classmethod
    async def stream_execution(
        cls,
        prompt: str,
        model: Optional[str] = None,
        conversation_id: Optional[str] = None,
        effort: Optional[str] = None,
        allow_tools: Optional[bool] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute agy.exe with stream-json output and yield parsed events.
        Protected by concurrency semaphore and per-request timeout.
        """
        resolved_model = cls.resolve_effective_model(model)
        cmd = [
            AGY_BIN_PATH,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--model",
            resolved_model,
        ]

        if allow_tools is None:
            use_tools = get_setting("allow_tool_execution", "0") == "1"
        else:
            use_tools = allow_tools

        if use_tools:
            cmd.append("--dangerously-skip-permissions")

        if effort and effort in ("low", "medium", "high", "xhigh", "max"):
            cmd.extend(["--effort", effort])

        if conversation_id:
            cmd.extend(["--conversation", conversation_id])

        logger.info(f"Executing AGY CLI: model={resolved_model}, conv_id={conversation_id}")

        semaphore = cls._get_semaphore()
        async with semaphore:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            current_conv_id = conversation_id
            full_text_parts: List[str] = []
            deadline = time.monotonic() + max(10, AGY_TIMEOUT_SECONDS)

            try:
                assert process.stdout is not None
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"AGY CLI melebihi batas waktu {AGY_TIMEOUT_SECONDS} detik.")

                    line_bytes = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
                    if not line_bytes:
                        break

                    line_str = line_bytes.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        continue

                    try:
                        event_data = json.loads(line_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = event_data.get("event")

                    if event_type == "init":
                        current_conv_id = event_data.get("conversation_id")
                        yield {
                            "type": "init",
                            "conversation_id": current_conv_id,
                        }

                    elif event_type == "step_update":
                        step = event_data.get("step_update", {})
                        if step.get("step_type") == "agent_response":
                            text_delta = step.get("text_delta")
                            if text_delta:
                                full_text_parts.append(text_delta)
                                yield {
                                    "type": "delta",
                                    "content": text_delta,
                                    "conversation_id": current_conv_id,
                                }

                    elif event_type == "result":
                        res = event_data.get("result", {})
                        current_conv_id = res.get("conversation_id") or current_conv_id
                        usage_data = res.get("usage", {})
                        final_usage = {
                            "prompt_tokens": usage_data.get("input_tokens", 0),
                            "completion_tokens": usage_data.get("output_tokens", 0),
                            "total_tokens": usage_data.get("total_tokens", 0),
                        }
                        full_response = res.get("response", "".join(full_text_parts))

                        yield {
                            "type": "result",
                            "response": full_response,
                            "conversation_id": current_conv_id,
                            "usage": final_usage,
                            "duration_seconds": res.get("duration_seconds", 0.0),
                        }

                returncode = await process.wait()
                if returncode != 0:
                    stderr_bytes = await process.stderr.read() if process.stderr else b""
                    stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
                    raise RuntimeError(f"AGY CLI error (code {returncode}): {stderr_text or 'Unknown CLI failure'}")

            except Exception as e:
                logger.error(f"Error reading agy process stdout: {e}")
                if process.returncode is None:
                    try:
                        process.kill()
                        await process.wait()
                    except Exception:
                        pass
                raise

    @classmethod
    async def run_single(
        cls,
        prompt: str,
        model: Optional[str] = None,
        conversation_id: Optional[str] = None,
        effort: Optional[str] = None,
        allow_tools: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Execute agy and collect full response non-streaming."""
        full_text = ""
        final_conv_id = conversation_id
        final_usage: Dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        duration = 0.0

        async for ev in cls.stream_execution(
            prompt=prompt,
            model=model,
            conversation_id=conversation_id,
            effort=effort,
            allow_tools=allow_tools,
        ):
            ev_type = ev.get("type")
            if ev_type == "init":
                final_conv_id = ev.get("conversation_id")
            elif ev_type == "delta":
                full_text += ev.get("content", "")
            elif ev_type == "result":
                full_text = ev.get("response", full_text)
                final_conv_id = ev.get("conversation_id", final_conv_id)
                final_usage = ev.get("usage", final_usage)
                duration = ev.get("duration_seconds", 0.0)

        return {
            "response": full_text,
            "conversation_id": final_conv_id or str(uuid.uuid4()),
            "usage": final_usage,
            "duration_seconds": duration,
        }

    @classmethod
    async def list_live_models(cls) -> List[Dict[str, str]]:
        """Query `agy models` live from the CLI binary, falling back to static list."""
        try:
            process = await asyncio.create_subprocess_exec(
                AGY_BIN_PATH,
                "models",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, _ = await asyncio.wait_for(process.communicate(), timeout=15.0)
            if process.returncode == 0 and stdout_bytes:
                models: List[Dict[str, str]] = []
                for line in stdout_bytes.decode("utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or "\t" not in line:
                        continue
                    model_id, label = line.split("\t", 1)
                    models.append({"id": model_id.strip(), "label": label.strip()})
                if models:
                    return models
        except Exception as e:
            logger.warning(f"Failed to query live agy models, using built-in list: {e}")

        return [{"id": m, "label": m} for m in AGY_SUPPORTED_MODELS]

    @classmethod
    async def ping_model(cls, model: str) -> Dict[str, Any]:
        """Run a lightweight live connectivity/latency test against a specific model."""
        resolved = cls.resolve_effective_model(model)
        start = time.perf_counter()
        result = await cls.run_single(
            prompt="Reply only with: OK",
            model=resolved,
            allow_tools=False,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "ok": True,
            "model": resolved,
            "latency_ms": latency_ms,
            "reply": result.get("response", "").strip(),
            "usage": result.get("usage", {}),
        }
