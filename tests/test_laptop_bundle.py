import importlib.util
import socket
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_free_port_skips_one_in_use():
    run_demo = load(ROOT / "scripts" / "laptop" / "run_demo.py")
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        assert run_demo.free_port(port) > port


def test_zip_keeps_launchers_runnable(tmp_path):
    make_bundle = load(ROOT / "scripts" / "make_bundle.py")
    folder = tmp_path / "val-demo"
    (folder / "uv" / "linux").mkdir(parents=True)
    (folder / "START-LINUX.sh").write_text("#!/bin/sh\n")
    (folder / "README.txt").write_text("hello\n")
    (folder / "uv" / "linux" / "uv").write_text("binary\n")
    target = tmp_path / "out.zip"
    make_bundle.write_zip(folder, target)
    with zipfile.ZipFile(target) as bundle:
        modes = {i.filename: (i.external_attr >> 16) & 0o777 for i in bundle.infolist()}
    assert modes["val-demo/START-LINUX.sh"] == 0o755
    assert modes["val-demo/uv/linux/uv"] == 0o755
    assert modes["val-demo/README.txt"] == 0o644
