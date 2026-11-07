"""Build the demo zip for someone else's laptop: unzip, double-click, and it runs.

It holds the light scene and what the backend needs, but no torch or training code's dependencies,
and a copy of uv for each system, which sets up Python inside the folder on the first run.
The zip holds Valmet's data, so it stays out of git and goes only where they allow.
"""

import argparse
import hashlib
import shutil
import stat
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAPTOP = ROOT / "scripts" / "laptop"
UV_VERSION = "0.11.7"
UV_FILES = {
    "windows": "uv-x86_64-pc-windows-msvc.zip",
    "mac-arm": "uv-aarch64-apple-darwin.tar.gz",
    "mac-intel": "uv-x86_64-apple-darwin.tar.gz",
    "linux": "uv-x86_64-unknown-linux-gnu.tar.gz",
}
# Each list must install on these, as wheels, or it's reported before anyone is handed the zip.
PLATFORMS = [
    "x86_64-pc-windows-msvc",
    "aarch64-apple-darwin",
    "x86_64-apple-darwin",
    "x86_64-unknown-linux-gnu",
]
LISTS = ["requirements", "requirements-voice", "requirements-export"]
LAUNCHERS = ["START-LINUX.sh", "START-MAC.command", "START-WINDOWS.bat"]
SCENE_FILES = [
    "assets_mapped.json",
    "assets_final.json",
    "splat_labels.npy",
    "shapes.json",
    "nav_grid.npz",
]


def fetch_uv(platform: str, file_name: str, cache: Path, out: Path) -> None:
    """Put the checked uv binary for one system in the bundle."""
    url = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/{file_name}"
    archive = cache / f"{UV_VERSION}-{file_name}"
    if not archive.exists():
        cache.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, archive)
    with urllib.request.urlopen(f"{url}.sha256") as reply:
        expected = reply.read().decode().split()[0]
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        archive.unlink()
        raise SystemExit(f"{file_name} doesn't match its checksum.")
    target = out / "uv" / platform
    target.mkdir(parents=True)
    if file_name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            (target / "uv.exe").write_bytes(bundle.read("uv.exe"))
    else:
        with tarfile.open(archive) as bundle:
            member = next(m for m in bundle.getmembers() if m.name.endswith("/uv"))
            (target / "uv").write_bytes(bundle.extractfile(member).read())


def compile_lists(out: Path) -> None:
    """Pin every package, for every system, and check each has wheels so no compiler is needed."""
    for name in LISTS:
        source = LAPTOP / f"{name}.in"
        pinned = out / f"{name}.txt"
        base = [
            "uv",
            "pip",
            "compile",
            "--no-config",
            "--quiet",
            "--python-version",
            "3.12",
            str(source),
        ]
        subprocess.run(base + ["--universal", "-o", str(pinned)], check=True)
        for platform in PLATFORMS:
            done = subprocess.run(
                base + ["--python-platform", platform, "--only-binary", ":all:", "-o", "/dev/null"],
                capture_output=True,
                text=True,
            )
            if done.returncode:
                print(f"WARNING: {name} won't install on {platform}:\n{done.stderr[-500:]}")


def write_zip(folder: Path, target: Path) -> None:
    """Zip a folder, keeping the launchers runnable on Mac and Linux."""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
        for path in sorted(folder.rglob("*")):
            if path.is_dir():
                continue
            name = f"{folder.name}/{path.relative_to(folder).as_posix()}"
            info = zipfile.ZipInfo.from_file(path, name)
            info.compress_type = zipfile.ZIP_DEFLATED
            runnable = path.name in LAUNCHERS or path.name == "uv"
            info.external_attr = ((0o755 if runnable else 0o644) | stat.S_IFREG) << 16
            with path.open("rb") as source, bundle.open(info, "w", force_zip64=True) as sink:
                shutil.copyfileobj(source, sink, 1024 * 1024)


def build(options: argparse.Namespace) -> Path:
    out = options.out / "val-demo"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    skip = shutil.ignore_patterns("__pycache__", "*.pyc", ".cert", "serve_on_port*")
    shutil.copytree(ROOT / "app", out / "app", ignore=skip)
    shutil.copytree(ROOT / "web", out / "web", ignore=skip)
    for name in [*LAUNCHERS, "run_demo.py", "README.txt"]:
        shutil.copy(LAPTOP / name, out / name)

    demo = out / "demo"
    demo.mkdir()
    for name in SCENE_FILES:
        shutil.copy(options.scene_dir / name, demo / name)
    shutil.copy(options.scene, demo / "light_full.ply")
    shutil.copytree(options.pieces, demo / "pieces")
    shutil.copytree(options.bim, demo / "bim")
    shutil.copytree(options.highlights, demo / "highlights")
    shutil.copytree(options.whisper, demo / "whisper", symlinks=False)

    (out / "data").mkdir()
    packs = sorted(options.excel_dir.glob("*.xlsx"))
    if not packs:
        raise SystemExit(f"No Excel pack in {options.excel_dir}: Val would have no records.")
    for pack in packs:
        shutil.copy(pack, out / "data" / pack.name)

    compile_lists(out)
    for platform, file_name in UV_FILES.items():
        fetch_uv(platform, file_name, options.out / ".uv-downloads", out)
    target = options.out / "val-demo.zip"
    write_zip(out, target)
    return target


def main() -> None:
    scene = ROOT / "data" / "scene" / "equipment_room"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--scene-dir", type=Path, default=scene, help="the mapped objects and floor"
    )
    parser.add_argument("--scene", type=Path, default=scene / "light_full.ply")
    parser.add_argument("--pieces", type=Path, default=scene / "cut_light")
    parser.add_argument("--bim", type=Path, default=scene / "bim")
    parser.add_argument("--highlights", type=Path, default=scene / "highlights")
    parser.add_argument(
        "--whisper", type=Path, default=ROOT / "data" / "models" / "whisper-base.en"
    )
    parser.add_argument("--excel-dir", type=Path, default=ROOT / "data")
    target = build(parser.parse_args())
    print(f"{target}: {target.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
