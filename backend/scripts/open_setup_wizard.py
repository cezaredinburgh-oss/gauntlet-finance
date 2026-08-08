"""Start the API (if needed) and open the Google Sheets setup wizard in a browser."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Open the setup wizard")
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--no-start", action="store_true", help="Only open browser")
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    url = f"{base}/setup"

    def up() -> bool:
        try:
            r = httpx.get(f"{base}/health", timeout=1.5)
            return r.status_code == 200
        except Exception:
            return False

    proc = None
    if not args.no_start and not up():
        print(f"Starting API on port {args.port}…")
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
            ],
            cwd=str(_ROOT),
            env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(_ROOT)},
        )
        for _ in range(40):
            if up():
                break
            time.sleep(0.25)
        else:
            print("API did not become ready in time. Start it manually:")
            print(f'  cd "{_ROOT}"')
            print(f'  $env:PYTHONPATH = "."')
            print(f"  uvicorn backend.api.main:app --reload --port {args.port}")
            return 1

    print(f"Opening {url}")
    webbrowser.open(url)
    print("Leave this terminal open while you use the wizard (if we started the server).")
    if proc is not None:
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
