"""Start the demo on this machine, and open it in the browser. Ctrl+C or closing this stops it.

Needs nothing but the Python the START script set up. Changes made in the demo last until it stops.
"""

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO = HERE / "demo"
READY_SECONDS = 180


def free_port(start: int) -> int:
    """Return the first free port from `start` up, as a judge's laptop may be using ours."""
    for port in range(start, start + 100):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit(f"No free port from {start} up.")


def is_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as reply:
            return reply.status == 200
    except (urllib.error.URLError, OSError):
        return False


def wait_until_up(url: str, processes: list[subprocess.Popen], log: Path) -> None:
    deadline = time.monotonic() + READY_SECONDS
    while time.monotonic() < deadline:
        if is_up(url):
            return
        if any(process.poll() is not None for process in processes):
            break
        time.sleep(0.5)
    lines = log.read_text(errors="replace").splitlines()[-15:]
    raise SystemExit("The demo didn't start. The end of demo.log:\n" + "\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser")
    options = parser.parse_args()

    api_port = free_port(8001)
    view_port = free_port(api_port + 1)
    env = {
        **os.environ,
        "SCENE_PLY": str(DEMO / "light_full.ply"),
        "SCENE_ASSETS": str(DEMO / "assets_mapped.json"),
        "SCENE_GRID": str(DEMO / "nav_grid.npz"),
        "STT_MODEL": str(DEMO / "whisper"),
    }
    env.pop("DATABASE_URL", None)  # This demo keeps changes only until it stops.
    log_path = HERE / "demo.log"
    log = log_path.open("w")
    processes = []
    try:
        processes.append(
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.api.main:app"]
                + ["--host", "127.0.0.1", "--port", str(api_port)],
                cwd=HERE,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        )
        wait_until_up(f"http://127.0.0.1:{api_port}/api/assets", processes, log_path)
        processes.append(
            subprocess.Popen(
                [sys.executable, str(HERE / "web" / "serve.py")]
                + ["--scene", str(DEMO / "pieces" / "base.ply")]
                + ["--assets", str(DEMO / "assets_mapped.json")]
                + ["--shapes", str(DEMO / "shapes.json")]
                + ["--pieces", str(DEMO / "pieces")]
                + ["--bim", str(DEMO / "bim")]
                + ["--highlights", str(DEMO / "highlights")]
                + ["--host", "127.0.0.1", "--port", str(view_port)]
                + ["--api-port", str(api_port)],
                cwd=HERE,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        )
        address = f"http://localhost:{view_port}/"
        wait_until_up(address, processes, log_path)
        print(f"\nThe demo is running at {address}")
        print("Press the Demo button under Actions for a guided tour.")
        print("Leave this window open. Press Ctrl+C or close it to stop.\n", flush=True)
        if not options.no_browser:
            webbrowser.open(address + "?tour")  # the tutorial is offered on every start
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        print("Something stopped. See demo.log.")
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            process.terminate()
        log.close()


if __name__ == "__main__":
    main()
