import getpass
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

from app.config import AGY_BIN_PATH, BASE_DIR, PORT, get_local_lan_ip
from app.database import get_setting, set_setting
from app.tunnel import tunnel_manager

TASK_NAME = "AGY-Router-Gateway"
LINUX_SERVICE_NAME = "agy-router"
MACOS_LABEL = "com.kikik27.agy-router"


def _is_wsl() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        rel = platform.release().lower()
        if "microsoft" in rel or "wsl" in rel:
            return True
        proc_ver = Path("/proc/version")
        if proc_ver.exists():
            txt = proc_ver.read_text(encoding="utf-8", errors="ignore").lower()
            return "microsoft" in txt or "wsl" in txt
    except Exception:
        pass
    return False


def _get_venv_python() -> str:
    if sys.platform == "win32":
        cand = BASE_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        cand = BASE_DIR / ".venv" / "bin" / "python"
    return str(cand) if cand.exists() else sys.executable


def _check_port_open(port: int = PORT) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False
    finally:
        sock.close()


def detect_device(port: int = PORT) -> Dict[str, Any]:
    """Detect current OS, architecture, WSL status, binaries, and native service backend."""
    if sys.platform == "win32":
        os_type = "windows"
        service_backend = "windows-task-scheduler"
    elif sys.platform == "darwin":
        os_type = "macos"
        service_backend = "macos-launchd"
    else:
        os_type = "linux"
        service_backend = "linux-systemd-user"

    agy_found = bool(
        (AGY_BIN_PATH and os.path.exists(AGY_BIN_PATH)) or shutil.which("agy")
    )
    cf_bin = tunnel_manager.find_binary()

    return {
        "os_type": os_type,
        "os_display": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "hostname": platform.node(),
        "username": getpass.getuser(),
        "is_wsl": _is_wsl(),
        "python_version": platform.python_version(),
        "venv_python": _get_venv_python(),
        "repo_dir": str(BASE_DIR),
        "lan_ip": get_local_lan_ip(),
        "port": port,
        "agy_binary": AGY_BIN_PATH,
        "agy_found": agy_found,
        "cloudflared_binary": cf_bin or "",
        "cloudflared_found": bool(cf_bin),
        "service_backend": service_backend,
        "server_running": _check_port_open(port),
    }


def _tail_log_file(max_lines: int = 25) -> List[str]:
    log_file = BASE_DIR / "logs" / "agy-router.log"
    if not log_file.exists():
        return []
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-max_lines:]
    except Exception:
        return []


def get_service_status(port: int = PORT) -> Dict[str, Any]:
    """Inspect native background service status across Windows, Linux, and macOS."""
    device = detect_device(port=port)
    os_type = device["os_type"]
    installed = False
    running = False
    state_label = "Not Installed"
    logs: List[str] = []

    if os_type == "windows":
        try:
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; if ($t) {{ $t.State }} else {{ 'NOT_FOUND' }}",
                ],
                capture_output=True,
                text=True,
                timeout=8,
            )
            out = (proc.stdout or "").strip()
            if out and out != "NOT_FOUND":
                installed = True
                state_label = out
                running = out.lower() == "running" or device["server_running"]
        except Exception as e:
            state_label = f"Check error: {e}"
        logs = _tail_log_file(25)

    elif os_type == "linux":
        unit_file = Path.home() / ".config" / "systemd" / "user" / f"{LINUX_SERVICE_NAME}.service"
        installed = unit_file.exists() or Path(f"/etc/systemd/system/{LINUX_SERVICE_NAME}.service").exists()
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "is-active", LINUX_SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=5,
            )
            out = (proc.stdout or "").strip()
            if proc.returncode == 0 and out == "active":
                installed = True
                running = True
                state_label = "active"
            elif installed:
                state_label = out or "inactive"
        except Exception as e:
            if installed:
                state_label = f"Check error: {e}"
        try:
            jproc = subprocess.run(
                ["journalctl", "--user", "-u", LINUX_SERVICE_NAME, "-n", "25", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if jproc.returncode == 0 and jproc.stdout:
                logs = jproc.stdout.splitlines()
        except Exception:
            logs = _tail_log_file(25)

    else:  # macos
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"
        installed = plist_path.exists()
        if installed:
            try:
                proc = subprocess.run(
                    ["launchctl", "list", MACOS_LABEL],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                running = proc.returncode == 0
                state_label = "loaded" if running else "unloaded"
            except Exception:
                state_label = "installed"
        logs = _tail_log_file(25)

    health_ok = False
    if device["server_running"]:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
            health_ok = r.status_code == 200
        except Exception:
            health_ok = False

    return {
        "backend": device["service_backend"],
        "installed": installed,
        "running": running or health_ok,
        "state": state_label,
        "health_ok": health_ok,
        "logs": logs,
    }


def _install_macos_service() -> str:
    launch_dir = Path.home() / "Library" / "LaunchAgents"
    launch_dir.mkdir(parents=True, exist_ok=True)
    plist_path = launch_dir / f"{MACOS_LABEL}.plist"
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    venv_py = _get_venv_python()

    plist_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{MACOS_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{venv_py}</string>
        <string>{BASE_DIR / 'run.py'}</string>
        <string>--log-file</string>
        <string>{log_dir / 'agy-router.log'}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{BASE_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""
    plist_path.write_text(plist_xml, encoding="utf-8")
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    res = subprocess.run(["launchctl", "load", "-w", str(plist_path)], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr or res.stdout or "launchctl load gagal")
    return f"LaunchAgent terpasang di {plist_path}"


def install_service(enable_tunnel: bool = False) -> Dict[str, Any]:
    """Install and start the 24/7 native background service for the detected OS."""
    if enable_tunnel:
        set_setting("tunnel_autostart", "1")

    device = detect_device()
    os_type = device["os_type"]
    output = ""

    if os_type == "windows":
        script = BASE_DIR / "deploy" / "windows" / "install-windows-service.ps1"
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=90,
        )
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            raise RuntimeError(output or "Gagal memasang Windows Scheduled Task.")
    elif os_type == "linux":
        script = BASE_DIR / "deploy" / "linux" / "install-systemd.sh"
        proc = subprocess.run(
            ["bash", str(script), "--user"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            raise RuntimeError(output or "Gagal memasang Linux systemd service.")
    else:
        output = _install_macos_service()

    status = get_service_status()
    status["message"] = output
    return status


def uninstall_service() -> Dict[str, Any]:
    """Stop and remove the 24/7 native background service for the detected OS."""
    device = detect_device()
    os_type = device["os_type"]
    output = ""

    if os_type == "windows":
        script = BASE_DIR / "deploy" / "windows" / "uninstall-windows-service.ps1"
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            raise RuntimeError(output or "Gagal menghapus Windows Scheduled Task.")
    elif os_type == "linux":
        script = BASE_DIR / "deploy" / "linux" / "uninstall-systemd.sh"
        proc = subprocess.run(
            ["bash", str(script), "--user"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            raise RuntimeError(output or "Gagal menghapus Linux systemd service.")
    else:
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"
        if plist_path.exists():
            subprocess.run(["launchctl", "unload", "-w", str(plist_path)], capture_output=True)
            plist_path.unlink(missing_ok=True)
            output = "LaunchAgent macOS dihapus."

    status = get_service_status()
    status["message"] = output
    return status


def start_background(port: int = PORT) -> Dict[str, Any]:
    """Launch AGY Router detached in the background on the current device."""
    if _check_port_open(port):
        return {"already_running": True, "port": port, "log_file": str(BASE_DIR / "logs" / "agy-router.log")}

    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "agy-router.log"
    venv_py = _get_venv_python()

    cmd = [venv_py, str(BASE_DIR / "run.py"), "--port", str(port), "--log-file", str(log_file)]
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        subprocess.Popen(cmd, cwd=str(BASE_DIR), creationflags=creationflags, close_fds=True)
    else:
        subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if _check_port_open(port):
            return {"already_running": False, "started": True, "port": port, "log_file": str(log_file)}
        time.sleep(0.35)

    return {"already_running": False, "started": False, "port": port, "log_file": str(log_file)}


def stop_background() -> Dict[str, Any]:
    """Stop any background `run.py` processes belonging to this repository."""
    stopped = 0
    if sys.platform == "win32":
        repo_escaped = str(BASE_DIR).replace("'", "''")
        ps = (
            f"$procs = Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | "
            f"Where-Object {{ $_.CommandLine -and $_.CommandLine.Contains('{repo_escaped}') -and $_.CommandLine.Contains('run.py') }}; "
            f"foreach ($p in $procs) {{ Stop-Process -Id $p.ProcessId -Force; Write-Output $p.ProcessId }}"
        )
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
        stopped = len([l for l in (proc.stdout or "").splitlines() if l.strip().isdigit()])
    else:
        proc = subprocess.run(["pkill", "-f", str(BASE_DIR / "run.py")], capture_output=True, text=True)
        if proc.returncode == 0:
            stopped = 1
    return {"stopped_count": stopped}
