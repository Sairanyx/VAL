"""Build the simulated BIM model:

python -m app.bim SCENE.ply ASSETS.json SHAPES.json OUT_DIR \\
    [--labels SPLAT_LABELS.npy --label-assets ASSETS_FINAL.json] [--pieces CUT_DIR]

Writes OUT_DIR/model.ifc (IFC4) and OUT_DIR/bim.json for the viewer. With labels, each object also
gets a scan surface mesh (OUT_DIR/meshes.bin, and in the IFC) and its own true-colour splats in
OUT_DIR/splats/: one file per object, and one per IFC class for objects that can't move.
Labels must index SCENE in the order of --label-assets, as from the extraction.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from app.bim.ifc import write_ifc
from app.bim.model import build_model
from app.bim.room import estimate_room
from app.bim.shapes import MIN_OPACITY, object_mesh
from app.scene.load import Splats, read_splats, write_splats


def object_splats(
    scene: Splats, labels: np.ndarray, label_assets: list[dict], pieces: dict[str, Splats]
) -> dict[str, Splats]:
    """Each object's own splats: its cut piece when there is one, otherwise its labelled splats."""
    if labels.shape != (len(scene),):
        raise ValueError("Labels must index every splat of the scene")
    order = np.argsort(labels, kind="stable")
    bounds = np.searchsorted(labels[order], np.arange(len(label_assets) + 1))
    out = {}
    for index, asset in enumerate(label_assets):
        members = order[bounds[index] : bounds[index + 1]]
        if len(members) != asset["splats"]:
            raise ValueError("Splat counts differ: use the extraction's scene and asset order")
        out[asset["object_id"]] = scene[members]
    out.update(pieces)
    return out


def export_shapes(model: dict, splats: dict[str, Splats], out: Path) -> dict[str, dict]:
    """Write meshes.bin and splat files, and note in each element where its data is."""
    folder = out / "splats"
    folder.mkdir(parents=True, exist_ok=True)
    groups = defaultdict(list)
    vertex_blocks, face_blocks, meshes = [], [], {}
    vertex_count = face_count = 0
    for element in model["elements"]:
        object_id = element["object_id"]
        if object_id not in splats or not len(splats[object_id]):
            continue
        own = splats[object_id]
        write_splats(own, folder / f"{object_id}.ply")
        element["splats"] = f"{object_id}.ply"
        movable = element["psets"]["Valmet_Identification"]["Mobility"] == "movable"
        if not movable:
            element["splat_group"] = f"class-{element['ifc_class']}.ply"
            groups[element["splat_group"]].append(own)
        mesh = object_mesh(own.positions[own.opacities > MIN_OPACITY])
        if mesh:
            meshes[object_id] = mesh
            element["mesh"] = {
                "vertices": [vertex_count, len(mesh["vertices"])],
                "faces": [face_count, len(mesh["faces"])],
            }
            vertex_blocks.append(mesh["vertices"])
            face_blocks.append(mesh["faces"])
            vertex_count += len(mesh["vertices"])
            face_count += len(mesh["faces"])
    for name, parts in groups.items():
        write_splats(Splats(np.concatenate([p.data for p in parts])), folder / name)
    vertices = np.concatenate(vertex_blocks).astype("<f4").tobytes() if vertex_blocks else b""
    faces = np.concatenate(face_blocks).astype("<u4").tobytes() if face_blocks else b""
    (out / "meshes.bin").write_bytes(vertices + faces)
    model["meshes"] = {"file": "meshes.bin", "vertices": vertex_count, "faces": face_count}
    return meshes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("assets", type=Path)
    parser.add_argument("shapes", type=Path, help="fitted shapes; a missing file means boxes only")
    parser.add_argument("out", type=Path)
    parser.add_argument("--labels", type=Path, help="splat_labels.npy from the extraction")
    parser.add_argument("--label-assets", type=Path, help="assets file the labels index")
    parser.add_argument("--pieces", type=Path, help="cut folder from app.scene.split_movable")
    args = parser.parse_args()
    if bool(args.labels) != bool(args.label_assets):
        parser.error("--labels and --label-assets go together")
    assets = json.loads(args.assets.read_text())
    shapes = json.loads(args.shapes.read_text()) if args.shapes.exists() else {}
    scene = read_splats(args.scene)
    room = estimate_room(
        scene.positions, scene.opacities, assets["up"], assets["floor_height_along_up"]
    )
    model = build_model(assets, shapes, room)
    args.out.mkdir(parents=True, exist_ok=True)
    meshes = {}
    if args.labels:
        pieces = {}
        if args.pieces:
            for object_id in json.loads((args.pieces / "pieces.json").read_text()):
                pieces[object_id] = read_splats(args.pieces / "pieces" / f"{object_id}.ply")
        splats = object_splats(
            scene,
            np.load(args.labels, allow_pickle=False),
            json.loads(args.label_assets.read_text())["assets"],
            pieces,
        )
        meshes = export_shapes(model, splats, args.out)
        # Rebuild with the meshes, keeping the file locations export_shapes added.
        located = {e["guid"]: e for e in model["elements"]}
        meshed = build_model(assets, shapes, room, meshes)
        for element in meshed["elements"]:
            for key in ("splats", "splat_group", "mesh"):
                if key in located[element["guid"]]:
                    element[key] = located[element["guid"]][key]
        meshed["meshes"] = model["meshes"]
        model = meshed
    write_ifc(model, args.out / "model.ifc", meshes=meshes)
    (args.out / "bim.json").write_text(json.dumps(model))
    counts = Counter(element["ifc_class"] for element in model["elements"])
    print(
        json.dumps(
            {
                "elements": len(model["elements"]),
                "meshed": len(meshes),
                "mesh_triangles": model.get("meshes", {}).get("faces", 0),
                "room": room["faces"],
                "classes": counts,
            }
        )
    )


if __name__ == "__main__":
    main()
