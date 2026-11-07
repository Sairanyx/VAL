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
from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
CERT_DIR = WEB / ".cert"  # not in git


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
        return super().translate_path(path)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--scene", type=Path, required=True, help="splat .ply to show")
    p.add_argument("--assets", type=Path, default=ROOT / "fixtures/sample_assets.json")
    p.add_argument("--shapes", type=Path, help="fitted shapes for the objects view")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--https", action="store_true", help="serve HTTPS, needed for phone sensors")
    args = p.parse_args()

    for f in (args.scene, args.assets):
        if not f.is_file():
            p.error(f"not found: {f}")

    routes = {"/scene.ply": args.scene.resolve(), "/assets.json": args.assets.resolve()}
    if args.shapes:
        if not args.shapes.is_file():
            p.error(f"not found: {args.shapes}")
        routes["/shapes.json"] = args.shapes.resolve()
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
