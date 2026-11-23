import argparse
import sys
from pathlib import Path
import uvicorn
from app.config import HOST, PORT, get_local_lan_ip


def configure_log_file(log_path: str) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    log_stream = open(path, "a", encoding="utf-8", buffering=1)
    sys.stdout = log_stream
    sys.stderr = log_stream


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AGY Router Local AI Gateway")
    parser.add_argument("--host", default=HOST, help="Bind host (default from .env)")
    parser.add_argument("--port", type=int, default=PORT, help="Bind port (default from .env)")
    parser.add_argument("--log-file", default="", help="Optional log file path for background runs")
    args = parser.parse_args()

    if args.log_file:
        configure_log_file(args.log_file)

    lan_ip = get_local_lan_ip()
    print("=" * 64)
    print("  AGYRouter - Official Local AI Gateway (ToS-Compliant)")
    print("  Open Source by kikik27 -> https://github.com/kikik27/AGYRouter")
    print("=" * 64)
    print(f"  Dashboard (Local) : http://127.0.0.1:{args.port}/")
    print(f"  Dashboard (LAN)   : http://{lan_ip}:{args.port}/")
    print(f"  OpenAI Base URL   : http://127.0.0.1:{args.port}/v1")
    print(f"  Swagger API Docs  : http://127.0.0.1:{args.port}/docs")
    print(f"  Default Login     : password '123456' (ubah di menu Settings)")
    print("=" * 64)
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
