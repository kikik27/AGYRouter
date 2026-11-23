import argparse
import asyncio
import getpass
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import httpx
import uvicorn

from app.config import HOST, PORT
from app.database import (
    create_api_key,
    delete_api_key,
    get_db_path,
    get_setting,
    hash_password,
    init_db,
    list_api_keys,
    set_setting,
    update_api_key,
)
from app.service_manager import (
    detect_device,
    get_service_status,
    install_service,
    start_background,
    stop_background,
    uninstall_service,
)
from app.tunnel import tunnel_manager


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    try:
        ans = input(prompt + suffix).strip().lower()
    except EOFError:
        return default
    if not ans:
        return default
    return ans in ("y", "yes", "ya")


def cmd_setup(_args: argparse.Namespace) -> int:
    init_db()
    device = detect_device()
    print("=" * 64)
    print("  AGYRouter - Interactive CLI Setup Wizard")
    print("  Open Source by kikik27 -> https://github.com/kikik27/AGYRouter")
    print("=" * 64)
    print(f"  Device Terdeteksi : {device['os_display']} ({device['arch']})")
    print(f"  Hostname / User   : {device['hostname']} / {device['username']}")
    print(f"  Service Backend   : {device['service_backend']}")
    print(f"  LAN IP            : {device['lan_ip']}:{device['port']}")
    print(f"  AGY CLI Binary    : {'OK -> ' + device['agy_binary'] if device['agy_found'] else 'TIDAK DITEMUKAN'}")
    print("=" * 64)

    if not device["agy_found"]:
        print("\n[!] Peringatan: binary `agy` tidak ditemukan. Pastikan Antigravity CLI terinstall & sudah login.")

    # 1. Password admin
    if get_setting("is_default_password", "1") == "1":
        if _ask_yes_no("\n[1/4] Anda masih memakai password default '123456'. Ganti password admin sekarang?", True):
            while True:
                pw = getpass.getpass("      Password baru (min 4 karakter): ").strip()
                if len(pw) < 4:
                    print("      Password minimal 4 karakter.")
                    continue
                pw2 = getpass.getpass("      Konfirmasi password baru: ").strip()
                if pw != pw2:
                    print("      Konfirmasi tidak cocok, coba lagi.")
                    continue
                set_setting("password_hash", hash_password(pw))
                set_setting("is_default_password", "0")
                print("      [OK] Password admin diperbarui.")
                break

    # 2. API Key
    keys = list_api_keys()
    active_keys = [k for k in keys if k["is_active"]]
    print("\n[2/4] Status API Key:")
    if active_keys:
        print(f"      Key aktif tersedia: {active_keys[0]['name']} -> {active_keys[0]['key_value']}")
        if _ask_yes_no("      Buat API Key tambahan baru?", False):
            label = input("      Nama label key: ").strip() or "CLI Generated Key"
            k = create_api_key(label)
            print(f"      [OK] Key baru dibuat: {k['key_value']}")
    else:
        k = create_api_key("Default Local Key")
        print(f"      [OK] Key default dibuat: {k['key_value']}")

    # 3. Cloudflare Tunnel
    print("\n[3/4] Cloudflare Free Tunnel (Akses Publik HTTPS Gratis):")
    enable_tunnel = False
    if _ask_yes_no("      Pasang & aktifkan Cloudflare Tunnel otomatis saat server menyala?", False):
        enable_tunnel = True
        if not tunnel_manager.find_binary():
            print("      Mengunduh binary resmi cloudflared...")
            try:
                path = asyncio.run(tunnel_manager.install_binary())
                print(f"      [OK] cloudflared terpasang di {path}")
            except Exception as e:
                print(f"      [!] Gagal install cloudflared: {e}")
        mode = input("      Pilih mode tunnel [quick/token] (default: quick): ").strip().lower() or "quick"
        if mode == "token":
            tok = input("      Masukkan Cloudflare Tunnel Token: ").strip()
            dom = input("      Custom Domain URL (opsional, mis. https://agy.domain.com): ").strip()
            set_setting("tunnel_mode", "token")
            set_setting("tunnel_token", tok)
            set_setting("tunnel_custom_url", dom)
        else:
            set_setting("tunnel_mode", "quick")
        set_setting("tunnel_protocol", "http2")
        set_setting("tunnel_autostart", "1")
        print("      [OK] Cloudflare Tunnel auto-start diaktifkan (protocol=http2).")

    # 4. 24/7 Background Service
    print(f"\n[4/4] Background Service 24/7 ({device['service_backend']}):")
    if _ask_yes_no("      Install & jalankan AGY Router otomatis di background sekarang?", True):
        try:
            res = install_service(enable_tunnel=enable_tunnel)
            print(f"      [OK] Service terpasang! Status: {res['state']} (running={res['running']})")
        except Exception as e:
            print(f"      [!] Gagal install service: {e}")
    else:
        print("\nSetup selesai. Jalankan server kapan saja dengan: agy-router start")

    print(f"\nDashboard : http://127.0.0.1:{device['port']}/")
    print(f"OpenAI URL: http://127.0.0.1:{device['port']}/v1")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    init_db()
    d = detect_device()
    svc = get_service_status()
    agy_ver = "N/A"
    if d["agy_found"]:
        try:
            p = subprocess.run([d["agy_binary"], "--version"], capture_output=True, text=True, timeout=5)
            agy_ver = (p.stdout or p.stderr or "OK").strip().splitlines()[0]
        except Exception:
            agy_ver = "detected"

    print("=== AGY Router Device & Environment Doctor ===")
    print(f"OS              : {d['os_display']} ({d['os_type']}) | Arch: {d['arch']} | WSL: {d['is_wsl']}")
    print(f"Host / User     : {d['hostname']} / {d['username']}")
    print(f"Python / Venv   : {d['python_version']} ({d['venv_python']})")
    print(f"Repo Dir        : {d['repo_dir']}")
    print(f"SQLite DB       : {get_db_path()}")
    print(f"AGY Binary      : {'OK' if d['agy_found'] else 'MISSING'} -> {d['agy_binary']} ({agy_ver})")
    print(f"Cloudflared     : {'OK' if d['cloudflared_found'] else 'NOT INSTALLED'} -> {d['cloudflared_binary'] or '-'}")
    print(f"LAN IP / Port   : {d['lan_ip']}:{d['port']} (Listening: {d['server_running']})")
    print(f"Service Backend : {d['service_backend']} (Installed: {svc['installed']}, State: {svc['state']})")
    return 0 if d["agy_found"] else 1


def cmd_status(args: argparse.Namespace) -> int:
    init_db()
    port = args.port
    d = detect_device(port=port)
    svc = get_service_status(port=port)
    keys = list_api_keys()
    active_keys = [k for k in keys if k["is_active"]]

    print("=== AGY Router Status ===")
    print(f"Device          : {d['os_display']} ({d['arch']}) · {d['hostname']}")
    print(f"Server Port {port}: {'ONLINE' if d['server_running'] else 'OFFLINE'} (Health OK: {svc['health_ok']})")
    print(f"Local URL       : http://127.0.0.1:{port}/v1")
    print(f"LAN URL         : http://{d['lan_ip']}:{port}/v1")
    print(f"Active API Keys : {len(active_keys)} / {len(keys)}")
    if active_keys:
        print(f"Default Key     : {active_keys[0]['key_value']}")
    print(f"Service ({svc['backend']}): Installed={svc['installed']}, State={svc['state']}")
    print(f"Tunnel Autostart: {get_setting('tunnel_autostart', '0') == '1'} (Mode: {get_setting('tunnel_mode', 'quick')})")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    init_db()
    if args.tunnel:
        os.environ["AGY_DISABLE_AUTOSTART"] = "0"
        set_setting("tunnel_autostart", "1")
        if args.protocol:
            set_setting("tunnel_protocol", args.protocol)

    if args.background:
        res = start_background(port=args.port)
        if res.get("already_running"):
            print(f"[INFO] Server sudah berjalan di port {args.port}.")
        elif res.get("started"):
            print(f"[OK] AGY Router berjalan di background (port {args.port}). Log: {res['log_file']}")
        else:
            print(f"[!] Server diluncurkan di background, cek log: {res['log_file']}")
        return 0

    lan_ip = detect_device(port=args.port)["lan_ip"]
    print("=" * 64)
    print("  AGY Router - Official Local AI Gateway (ToS-Compliant)")
    print("  Open Source by kikik27 -> https://github.com/kikik27")
    print("=" * 64)
    print(f"  Dashboard (Local) : http://127.0.0.1:{args.port}/")
    print(f"  Dashboard (LAN)   : http://{lan_ip}:{args.port}/")
    print(f"  OpenAI Base URL   : http://127.0.0.1:{args.port}/v1")
    print("=" * 64)
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
    return 0


def cmd_stop(_args: argparse.Namespace) -> int:
    res = stop_background()
    print(f"[OK] Proses background dihentikan: {res['stopped_count']}")
    return 0


def cmd_keys(args: argparse.Namespace) -> int:
    init_db()
    action = args.keys_action

    if action == "list":
        keys = list_api_keys()
        if not keys:
            print("Belum ada API Key.")
            return 0
        for k in keys:
            status = "ACTIVE" if k["is_active"] else "DISABLED"
            print(f"- [{status}] {k['id']} | {k['name']} | {k['key_value']} | model={k['allowed_model']} | reqs={k['request_count']}")
        return 0

    if action == "create":
        k = create_api_key(args.name, allowed_model=args.model)
        print(f"[OK] API Key dibuat:\n  ID   : {k['id']}\n  Nama : {k['name']}\n  Key  : {k['key_value']}")
        return 0

    if action == "enable":
        updated = update_api_key(args.key_id, is_active=True)
        print(f"[OK] Key {args.key_id} diaktifkan." if updated else f"[!] Key {args.key_id} tidak ditemukan.")
        return 0 if updated else 1

    if action == "disable":
        updated = update_api_key(args.key_id, is_active=False)
        print(f"[OK] Key {args.key_id} dinonaktifkan." if updated else f"[!] Key {args.key_id} tidak ditemukan.")
        return 0 if updated else 1

    if action == "delete":
        ok = delete_api_key(args.key_id)
        print(f"[OK] Key {args.key_id} dihapus." if ok else f"[!] Key {args.key_id} tidak ditemukan.")
        return 0 if ok else 1

    return 1


def cmd_password(args: argparse.Namespace) -> int:
    init_db()
    pw = args.new_password
    if not pw:
        pw = getpass.getpass("Password admin baru (min 4 karakter): ").strip()
    if len(pw) < 4:
        print("[!] Password minimal 4 karakter.")
        return 1
    set_setting("password_hash", hash_password(pw))
    set_setting("is_default_password", "0")
    print("[OK] Password admin berhasil diperbarui.")
    return 0


def cmd_tunnel(args: argparse.Namespace) -> int:
    init_db()
    action = args.tunnel_action

    if action == "status":
        st = tunnel_manager.get_status()
        print(f"Installed       : {st['installed']} ({st['binary_path'] or '-'})")
        print(f"Saved Mode      : {st['saved_mode']} | Saved Protocol: {st['saved_protocol']}")
        print(f"Autostart       : {st['autostart']}")
        return 0

    if action == "install":
        path = asyncio.run(tunnel_manager.install_binary())
        print(f"[OK] cloudflared terpasang di: {path}")
        return 0

    if action == "start":
        mode = args.mode or get_setting("tunnel_mode", "quick")
        proto = args.protocol or get_setting("tunnel_protocol", "http2")
        token = args.token or get_setting("tunnel_token", "")
        custom_url = args.custom_url or get_setting("tunnel_custom_url", "")
        if args.autostart is not None:
            set_setting("tunnel_autostart", "1" if args.autostart else "0")

        async def _run_fg():
            st = await tunnel_manager.start(
                mode=mode,
                token=token,
                custom_url=custom_url,
                port=args.port,
                protocol=proto,
                auto_install=True,
            )
            print("=" * 64)
            print("  Cloudflare Tunnel AKTIF!")
            print(f"  Public URL  : {st.get('public_url') or '-'}")
            print(f"  OpenAI /v1  : {st.get('openai_base_url') or '-'}")
            print("  Tekan Ctrl+C untuk menghentikan tunnel.")
            print("=" * 64)
            try:
                while tunnel_manager.is_running():
                    await asyncio.sleep(1.0)
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                await tunnel_manager.stop()
                print("\n[OK] Tunnel dihentikan.")

        try:
            asyncio.run(_run_fg())
        except KeyboardInterrupt:
            pass
        return 0

    if action == "stop":
        print("Untuk menghentikan tunnel yang berjalan di server aktif, gunakan menu Tunnel di Web Dashboard.")
        return 0

    return 1


def cmd_service(args: argparse.Namespace) -> int:
    init_db()
    action = args.service_action
    d = detect_device()

    if action == "status":
        svc = get_service_status()
        print(f"Device  : {d['os_display']} ({d['arch']})")
        print(f"Backend : {svc['backend']}")
        print(f"Status  : Installed={svc['installed']} | Running={svc['running']} | State={svc['state']} | Health={svc['health_ok']}")
        return 0

    if action == "install":
        print(f"Memasang service 24/7 untuk {d['os_display']} ({d['service_backend']})...")
        res = install_service(enable_tunnel=args.tunnel)
        if res.get("message"):
            print(res["message"])
        print(f"[OK] Installed={res['installed']} | State={res['state']} | Health={res['health_ok']}")
        return 0

    if action == "uninstall":
        print(f"Menghapus service untuk {d['os_display']} ({d['service_backend']})...")
        res = uninstall_service()
        if res.get("message"):
            print(res["message"])
        print(f"[OK] Service dihapus (Installed={res['installed']}).")
        return 0

    if action == "logs":
        svc = get_service_status()
        if not svc["logs"]:
            print("Belum ada log service.")
        else:
            print("\n".join(svc["logs"]))
        return 0

    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agy-router",
        description="AGY Router CLI — Official ToS-Compliant Local AI Gateway (by kikik27)",
    )
    sub = parser.add_subparsers(dest="command")

    p_setup = sub.add_parser("setup", help="Interactive setup wizard (device auto-detect, key, tunnel, 24/7 service)")
    p_setup.set_defaults(func=cmd_setup)

    p_doctor = sub.add_parser("doctor", help="Diagnose OS, binaries, database, and ports")
    p_doctor.set_defaults(func=cmd_doctor)

    p_status = sub.add_parser("status", help="Show gateway, keys, and service status")
    p_status.add_argument("--port", type=int, default=PORT)
    p_status.set_defaults(func=cmd_status)

    p_start = sub.add_parser("start", help="Start AGY Router server")
    p_start.add_argument("--host", default=HOST)
    p_start.add_argument("--port", type=int, default=PORT)
    p_start.add_argument("--tunnel", action="store_true", help="Enable Cloudflare Tunnel auto-start")
    p_start.add_argument("--protocol", choices=["http2", "auto", "quic"], default="http2")
    p_start.add_argument("--background", action="store_true", help="Run detached in background")
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="Stop background AGY Router process")
    p_stop.set_defaults(func=cmd_stop)

    p_pw = sub.add_parser("password", help="Change dashboard admin password")
    p_pw.add_argument("new_password", nargs="?", default=None)
    p_pw.set_defaults(func=cmd_password)

    # Keys subcommands
    p_keys = sub.add_parser("keys", help="Manage sk-agy-... API keys")
    keys_sub = p_keys.add_subparsers(dest="keys_action", required=True)
    keys_sub.add_parser("list", help="List all API keys").set_defaults(func=cmd_keys)
    pk_create = keys_sub.add_parser("create", help="Create a new API key")
    pk_create.add_argument("name")
    pk_create.add_argument("--model", default="*")
    pk_create.set_defaults(func=cmd_keys)
    for act in ("enable", "disable", "delete"):
        pk = keys_sub.add_parser(act, help=f"{act.capitalize()} an API key")
        pk.add_argument("key_id")
        pk.set_defaults(func=cmd_keys)

    # Tunnel subcommands
    p_tun = sub.add_parser("tunnel", help="Manage free Cloudflare Tunnel")
    tun_sub = p_tun.add_subparsers(dest="tunnel_action", required=True)
    tun_sub.add_parser("status", help="Show tunnel config status").set_defaults(func=cmd_tunnel)
    tun_sub.add_parser("install", help="Download official cloudflared binary").set_defaults(func=cmd_tunnel)
    pt_start = tun_sub.add_parser("start", help="Start Cloudflare Tunnel in foreground")
    pt_start.add_argument("--mode", choices=["quick", "token"], default=None)
    pt_start.add_argument("--protocol", choices=["http2", "auto", "quic"], default=None)
    pt_start.add_argument("--token", default=None)
    pt_start.add_argument("--custom-url", default=None)
    pt_start.add_argument("--port", type=int, default=PORT)
    pt_start.add_argument("--autostart", action="store_true", default=None)
    pt_start.set_defaults(func=cmd_tunnel)
    tun_sub.add_parser("stop", help="Stop guidance").set_defaults(func=cmd_tunnel)

    # Service subcommands
    p_svc = sub.add_parser("service", help="Manage 24/7 OS background service (auto-detect Windows/Linux/macOS)")
    svc_sub = p_svc.add_subparsers(dest="service_action", required=True)
    svc_sub.add_parser("status", help="Show native service status").set_defaults(func=cmd_service)
    ps_inst = svc_sub.add_parser("install", help="Install & start 24/7 native service")
    ps_inst.add_argument("--tunnel", action="store_true", help="Enable Cloudflare Tunnel auto-start")
    ps_inst.set_defaults(func=cmd_service)
    svc_sub.add_parser("uninstall", help="Stop & remove native service").set_defaults(func=cmd_service)
    svc_sub.add_parser("logs", help="Show recent service logs").set_defaults(func=cmd_service)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
