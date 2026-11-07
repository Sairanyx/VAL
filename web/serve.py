"""Serve the web viewer on the local network. Standard library only, no internet needed.

    make web                                              # fake test scene + fixture
    make web SCENE="data/scene/Equipment Room.ply"        # the real scene
    uv run python web/serve.py --scene X.ply --assets Y.json

Then open http://localhost:8000 here, or http://<this machine's IP>:8000 on a tablet on the
same network.

Phones only allow motion sensors on HTTPS pages. `make web HTTPS=1` (or `--https`) serves HTTPS
with a self-signed certificate made in web/.cert/ on first use. The browser warns once; accept it.
"""

import argparse
import functools
import http.server
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
CERT_DIR = WEB / ".cert"  # not in git
API = "http://127.0.0.1:8001"


def tls_context() -> ssl.SSLContext:
    cert, key = CERT_DIR / "cert.pem", CERT_DIR / "key.pem"
    if not cert.exists():
        CERT_DIR.mkdir(exist_ok=True)
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30"]
            + ["-keyout", str(key), "-out", str(cert), "-subj", "/CN=plant-viewer"],
            check=True,
            capture_output=True,
        )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    return ctx


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, routes: dict[str, Path], **kwargs):
        self.routes = routes
        super().__init__(*args, directory=str(WEB), **kwargs)

    def translate_path(self, path: str) -> str:
        route = path.split("?", 1)[0]
        if route in self.routes:
            return str(self.routes[route])
        pieces = self.routes.get("/pieces/")
        if pieces and route.startswith("/pieces/"):
            return str(pieces / Path(route).name)
        highlights = self.routes.get("/highlights/")
        if highlights and route.startswith("/highlights/"):
            return str(highlights / Path(route).name)
        return super().translate_path(path)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def forward_to_api(self) -> None:
        """Pass /api to the backend, so a tablet needs one address, and HTTPS pages can reach it."""
        length = int(self.headers.get("Content-Length") or 0)
        request = urllib.request.Request(
            API + self.path,
            data=self.rfile.read(length) if length else None,
            headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
            method=self.command,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, body = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read()
        except urllib.error.URLError:
            status, body = 502, b'{"detail": "The backend isn\'t running: start it with make api"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self.forward_to_api()
        else:
            super().do_GET()

    def do_POST(self) -> None:
        if self.path.startswith("/api/"):
            self.forward_to_api()
        else:
            self.send_error(404)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--scene", type=Path, required=True, help="splat .ply to show")
    p.add_argument("--assets", type=Path, default=ROOT / "fixtures/sample_assets.json")
    p.add_argument("--shapes", type=Path, help="fitted shapes for the objects view")
    p.add_argument("--light", type=Path, help="lighter copy of the scene for phones and tablets")
    p.add_argument("--pieces", type=Path, help="folder from app.scene.split_movable")
    p.add_argument("--highlights", type=Path, help="segmented coloured splats from make highlights")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--https", action="store_true", help="serve HTTPS, needed for phone sensors")
    args = p.parse_args()

    for f in (args.scene, args.assets):
        if not f.is_file():
            p.error(f"not found: {f}")

    routes = {"/scene.ply": args.scene.resolve(), "/assets.json": args.assets.resolve()}
    if args.light:
        if not args.light.is_file():
            p.error(f"not found: {args.light}")
        routes["/scene-light.ply"] = args.light.resolve()
    if args.shapes:
        if not args.shapes.is_file():
            p.error(f"not found: {args.shapes}")
        routes["/shapes.json"] = args.shapes.resolve()
    if args.pieces:
        routes["/pieces.json"] = (args.pieces / "pieces.json").resolve()
        routes["/pieces/"] = (args.pieces / "pieces").resolve()
    if args.highlights:
        if not (args.highlights / "highlights.json").is_file():
            p.error(f"not found: {args.highlights / 'highlights.json'}; run make highlights")
        routes["/highlights.json"] = (args.highlights / "highlights.json").resolve()
        routes["/highlights/"] = args.highlights.resolve()
    handler = functools.partial(Handler, routes=routes)
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as srv:
        scheme = "https" if args.https else "http"
        if args.https:
            srv.socket = tls_context().wrap_socket(srv.socket, server_side=True)
        print(
            f"Viewer on {scheme}://localhost:{args.port}  "
            f"(scene: {args.scene}, assets: {args.assets})"
        )
        srv.serve_forever()


if __name__ == "__main__":
    main()
