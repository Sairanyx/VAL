"""Serve the web viewer on the local network. Standard library only, no internet needed.

    make web                                              # fake test scene + fixture
    make web SCENE="data/scene/Equipment Room.ply"        # the real scene
    uv run python web/serve.py --scene X.ply --assets Y.json

Then open http://localhost:8000 here, or http://<this machine's IP>:8000 on a tablet on the
same network.
"""

import argparse
import functools
import http.server
from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, routes: dict[str, Path], **kwargs):
        self.routes = routes
        super().__init__(*args, directory=str(WEB), **kwargs)

    def translate_path(self, path: str) -> str:
        route = path.split("?", 1)[0]
        if route in self.routes:
            return str(self.routes[route])
        return super().translate_path(path)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--scene", type=Path, required=True, help="splat .ply to show")
    p.add_argument("--assets", type=Path, default=ROOT / "fixtures/sample_assets.json")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()

    for f in (args.scene, args.assets):
        if not f.is_file():
            p.error(f"not found: {f}")

    routes = {"/scene.ply": args.scene.resolve(), "/assets.json": args.assets.resolve()}
    handler = functools.partial(Handler, routes=routes)
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as srv:
        print(
            f"Viewer on http://localhost:{args.port}  (scene: {args.scene}, assets: {args.assets})"
        )
        srv.serve_forever()


if __name__ == "__main__":
    main()
