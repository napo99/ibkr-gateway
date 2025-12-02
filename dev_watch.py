"""
Simple dev watcher to auto-restart the live server on file changes and
poke the reload token so the browser can auto-refresh.

Usage:
  uv run python dev_watch.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).parent
WATCH_PATHS = [
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "pyproject.toml",
    PROJECT_ROOT / "uv.lock",
]
RELOAD_TOKEN_PATH = PROJECT_ROOT / "output" / "reload.token"


def snapshot() -> Dict[Path, float]:
    """Collect mtimes for watched files."""
    mtimes: Dict[Path, float] = {}
    for path in WATCH_PATHS:
        if path.is_file():
            mtimes[path] = path.stat().st_mtime
        elif path.is_dir():
            for p in path.rglob("*.py"):
                try:
                    mtimes[p] = p.stat().st_mtime
                except FileNotFoundError:
                    continue
    return mtimes


def has_changes(prev: Dict[Path, float], curr: Dict[Path, float]) -> bool:
    if prev.keys() != curr.keys():
        return True
    for p, m in curr.items():
        if prev.get(p) != m:
            return True
    return False


def write_reload_token() -> str:
    token = str(int(time.time() * 1000))
    RELOAD_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    RELOAD_TOKEN_PATH.write_text(token, encoding="utf-8")
    return token


def start_server() -> subprocess.Popen:
    write_reload_token()
    print("[DEV] Starting server...")
    return subprocess.Popen(
        [sys.executable, "-m", "src.live_server"],
        cwd=PROJECT_ROOT,
    )


def stop_server(proc: subprocess.Popen):
    if proc.poll() is not None:
        return
    print("[DEV] Stopping server...")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def main():
    mtimes = snapshot()
    proc = start_server()
    try:
        while True:
            time.sleep(1)
            curr = snapshot()
            if has_changes(mtimes, curr):
                mtimes = curr
                stop_server(proc)
                write_reload_token()
                proc = start_server()
    except KeyboardInterrupt:
        pass
    finally:
        stop_server(proc)
        print("[DEV] Watcher stopped.")


if __name__ == "__main__":
    main()
