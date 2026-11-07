"""Build the simulated BIM model: python -m app.bim SCENE.ply ASSETS.json SHAPES.json OUT_DIR

Writes OUT_DIR/model.ifc (IFC4) and OUT_DIR/bim.json (the same elements, for the web viewer).
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from app.bim.ifc import write_ifc
from app.bim.model import build_model
from app.bim.room import estimate_room
from app.scene.load import read_splats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("assets", type=Path)
    parser.add_argument("shapes", type=Path, help="fitted shapes; a missing file means boxes only")
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    assets = json.loads(args.assets.read_text())
    shapes = json.loads(args.shapes.read_text()) if args.shapes.exists() else {}
    splats = read_splats(args.scene)
    room = estimate_room(
        splats.positions, splats.opacities, assets["up"], assets["floor_height_along_up"]
    )
    model = build_model(assets, shapes, room)
    args.out.mkdir(parents=True, exist_ok=True)
    write_ifc(model, args.out / "model.ifc")
    (args.out / "bim.json").write_text(json.dumps(model))
    counts = Counter(element["ifc_class"] for element in model["elements"])
    print(json.dumps({"elements": len(model["elements"]), "room": room, "classes": counts}))


if __name__ == "__main__":
    main()
