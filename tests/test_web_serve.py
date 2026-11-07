import functools
import http.server
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "web_serve", Path(__file__).parent.parent / "web" / "serve.py"
)
serve = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(serve)


class FakeApi(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        status = 409 if json.loads(body).get("blocked") else 200
        self.send_response(status)
        self.end_headers()
        self.wfile.write(json.dumps({"got": json.loads(body), "path": self.path}).encode())

    def log_message(self, *args):
        pass


def start(handler):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def viewer():
    server = start(functools.partial(serve.Handler, routes={}))
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def post(url, body):
    request = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    return urllib.request.urlopen(request, timeout=5)


def test_api_calls_pass_through_with_the_backend_status(viewer, monkeypatch):
    backend = start(FakeApi)
    monkeypatch.setattr(serve, "API", f"http://127.0.0.1:{backend.server_address[1]}")
    with post(f"{viewer}/api/route", {"a": 1}) as response:
        assert json.load(response) == {"got": {"a": 1}, "path": "/api/route"}
    with pytest.raises(urllib.error.HTTPError) as refused:
        post(f"{viewer}/api/route", {"blocked": True})
    assert refused.value.code == 409
    backend.shutdown()


def test_missing_backend_gets_a_clear_message(viewer, monkeypatch):
    monkeypatch.setattr(serve, "API", "http://127.0.0.1:9")
    with pytest.raises(urllib.error.HTTPError) as missing:
        post(f"{viewer}/api/route", {})
    assert missing.value.code == 502
    assert "make api" in json.load(missing.value)["detail"]


def test_highlight_files_are_served(tmp_path):
    (tmp_path / "highlights.json").write_text('{"obj-1": {"splats": 1}}')
    (tmp_path / "obj-1.ply").write_bytes(b"ply\n")
    server = start(
        functools.partial(
            serve.Handler,
            routes={"/highlights.json": tmp_path / "highlights.json", "/highlights/": tmp_path},
        )
    )
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(url + "/highlights.json") as response:
            assert "obj-1" in json.load(response)
        with urllib.request.urlopen(url + "/highlights/obj-1.ply") as response:
            assert response.read() == b"ply\n"
    finally:
        server.shutdown()
