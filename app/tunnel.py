import asyncio
import atexit
import logging
import os
import platform
import re
import shutil
import sys
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import httpx

from app.config import BASE_DIR, PORT
from app.database import get_setting

logger = logging.getLogger("agy_tunnel")

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
TRYCLOUDFLARE_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


class CloudflareTunnelManager:
    """Manages official cloudflared subprocess for free Quick Tunnels and Named Tunnels."""

    def __init__(self) -> None:
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader_tasks: List[asyncio.Task] = []
        self.mode: str = "quick"
        self.protocol: str = "http2"
        self.public_url: Optional[str] = None
        self.started_at: Optional[int] = None
        self.error: Optional[str] = None
        self.recent_logs: Deque[str] = deque(maxlen=60)

    def find_binary(self) -> Optional[str]:
        """Locate cloudflared binary from env override, PATH, or local bin/ folder."""
        env_path = os.getenv("CLOUDFLARED_PATH", "").strip()
        if env_path and os.path.exists(env_path):
            return env_path

        which_path = shutil.which("cloudflared")
        if which_path:
            return which_path

        exe_name = "cloudflared.exe" if sys.platform == "win32" else "cloudflared"
        local_bin = BASE_DIR / "bin" / exe_name
        if local_bin.exists():
            return str(local_bin)

        return None

    async def install_binary(self) -> str:
        """Download official cloudflared release binary into BASE_DIR/bin/."""
        if sys.platform == "darwin":
            raise RuntimeError("Pada macOS, install cloudflared melalui Homebrew: brew install cloudflared")

        machine = platform.machine().lower()
        if sys.platform == "win32":
            asset = "cloudflared-windows-amd64.exe" if ("64" in machine or "amd64" in machine) else "cloudflared-windows-386.exe"
            exe_name = "cloudflared.exe"
        elif sys.platform.startswith("linux"):
            if "aarch64" in machine or "arm64" in machine:
                asset = "cloudflared-linux-arm64"
            else:
                asset = "cloudflared-linux-amd64"
            exe_name = "cloudflared"
        else:
            raise RuntimeError(f"Platform tidak didukung untuk auto-install: {sys.platform}")

        url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{asset}"
        bin_dir = BASE_DIR / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        dest_path = bin_dir / exe_name
        tmp_path = bin_dir / f"{exe_name}.tmp"

        self.recent_logs.append(f"[installer] Mengunduh {url} ...")
        async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise RuntimeError(f"Gagal mengunduh cloudflared (HTTP {resp.status_code})")
                with open(tmp_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

        os.replace(tmp_path, dest_path)
        if sys.platform != "win32":
            os.chmod(dest_path, 0o755)

        self.recent_logs.append(f"[installer] Berhasil dipasang di {dest_path}")
        return str(dest_path)

    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def _read_stream(self, stream: Optional[asyncio.StreamReader], label: str) -> None:
        if stream is None:
            return
        try:
            while True:
                line_bytes = await stream.readline()
                if not line_bytes:
                    break
                raw_line = line_bytes.decode("utf-8", errors="replace").strip()
                clean_line = ANSI_RE.sub("", raw_line)
                if not clean_line:
                    continue
                self.recent_logs.append(f"[{label}] {clean_line}")
                if self.mode == "quick" and not self.public_url:
                    match = TRYCLOUDFLARE_RE.search(clean_line)
                    if match:
                        self.public_url = match.group(0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.recent_logs.append(f"[{label}] stream error: {e}")

    @staticmethod
    def _normalize_url(raw: Optional[str]) -> Optional[str]:
        val = (raw or "").strip().rstrip("/")
        if not val:
            return None
        if not val.startswith("http://") and not val.startswith("https://"):
            val = f"https://{val}"
        return val

    async def start(
        self,
        mode: str = "quick",
        token: Optional[str] = None,
        custom_url: Optional[str] = None,
        port: int = PORT,
        protocol: str = "http2",
        auto_install: bool = True,
    ) -> Dict[str, Any]:
        """Start cloudflared in quick or token mode, auto-installing binary if missing."""
        await self.stop()

        binary = self.find_binary()
        if not binary:
            if auto_install:
                binary = await self.install_binary()
            else:
                raise RuntimeError("Binary cloudflared belum terpasang. Jalankan install terlebih dahulu.")

        clean_mode = "token" if mode == "token" else "quick"
        clean_proto = protocol if protocol in ("http2", "auto", "quic") else "http2"
        proto_args = ["--protocol", clean_proto] if clean_proto in ("http2", "quic") else []

        if clean_mode == "token":
            clean_token = (token or "").strip()
            if not clean_token:
                raise RuntimeError("Tunnel Token wajib diisi untuk mode Named Tunnel.")
            cmd = [binary, "tunnel", "--no-autoupdate", *proto_args, "run", "--token", clean_token]
        else:
            cmd = [binary, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate", *proto_args]

        self.mode = clean_mode
        self.protocol = clean_proto
        self.public_url = self._normalize_url(custom_url) if clean_mode == "token" else None
        self.error = None
        self.started_at = int(time.time())
        self.recent_logs.clear()
        self.recent_logs.append(f"[tunnel] Memulai cloudflared ({clean_mode} mode, protocol={clean_proto})...")

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_tasks = [
            asyncio.create_task(self._read_stream(self._process.stdout, "stdout")),
            asyncio.create_task(self._read_stream(self._process.stderr, "stderr")),
        ]

        if clean_mode == "quick":
            deadline = time.monotonic() + 35.0
            while time.monotonic() < deadline:
                if self.public_url:
                    break
                if self._process.returncode is not None:
                    self.error = f"cloudflared berhenti mendadak (code {self._process.returncode})"
                    await self.stop()
                    raise RuntimeError(self.error)
                await asyncio.sleep(0.25)

            if not self.public_url:
                self.error = (
                    "Timeout menunggu URL trycloudflare.com (35s). "
                    "Pastikan koneksi internet lancar atau coba ganti protocol ke 'auto'/'http2'."
                )
                await self.stop()
                raise RuntimeError(self.error)
        else:
            await asyncio.sleep(2.5)
            if self._process and self._process.returncode is not None:
                self.error = f"Named Tunnel gagal dijalankan (code {self._process.returncode}). Periksa Token Anda."
                await self.stop()
                raise RuntimeError(self.error)

        return self.get_status()

    async def stop(self) -> Dict[str, Any]:
        """Stop running cloudflared process cleanly without wiping diagnostic logs."""
        proc = self._process
        self._process = None

        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            except Exception:
                pass

        for task in self._reader_tasks:
            if not task.done():
                task.cancel()
        self._reader_tasks.clear()

        self.public_url = None
        self.started_at = None
        return self.get_status()

    def stop_sync(self) -> None:
        """Synchronous cleanup hook registered via atexit."""
        proc = self._process
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def get_status(self) -> Dict[str, Any]:
        binary = self.find_binary()
        running = self.is_running()
        public_url = self.public_url if running else None
        openai_base_url = f"{public_url.rstrip('/')}/v1" if public_url else None
        saved_token = get_setting("tunnel_token", "")

        return {
            "installed": bool(binary),
            "binary_path": binary or "",
            "running": running,
            "mode": self.mode,
            "protocol": self.protocol,
            "public_url": public_url,
            "openai_base_url": openai_base_url,
            "started_at": self.started_at if running else None,
            "pid": self._process.pid if (running and self._process) else None,
            "error": self.error,
            "autostart": get_setting("tunnel_autostart", "0") == "1",
            "saved_mode": get_setting("tunnel_mode", "quick"),
            "saved_protocol": get_setting("tunnel_protocol", "http2"),
            "has_token": bool(saved_token),
            "saved_custom_url": get_setting("tunnel_custom_url", ""),
            "recent_logs": list(self.recent_logs),
        }


tunnel_manager = CloudflareTunnelManager()
atexit.register(tunnel_manager.stop_sync)
