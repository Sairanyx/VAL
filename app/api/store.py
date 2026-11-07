"""Scene objects and the change log. In memory for now, with the same interface for a database."""

import copy
import json
import math
from pathlib import Path

NEW_OBJECT_SIZE = 0.5


class ChangeError(ValueError):
    """A change that isn't allowed, such as moving a fixed object."""


def box_distance(asset: dict, point: tuple[float, float, float]) -> float:
    """Distance from a point to an object's box, 0 if the point is inside."""
    gaps = (
        max(low - p, 0.0, p - high)
        for low, p, high in zip(asset["bbox_min"], point, asset["bbox_max"], strict=True)
    )
    return math.hypot(*gaps)


class SceneStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.scene = json.loads(self.path.read_text())
        self.reset()

    def reset(self) -> None:
        """Restore the base scan's objects. The file itself is never overwritten."""
        self.assets = {a["object_id"]: copy.deepcopy(a) for a in self.scene["assets"]}
        for asset in self.assets.values():
            asset.setdefault("mobility", "unsure")
            asset.setdefault("status", "detected")
        self.changes: list[dict] = []

    def visible(self) -> list[dict]:
        return [a for a in self.assets.values() if a["status"] != "removed"]

    def get(self, object_id: str) -> dict | None:
        return self.assets.get(object_id)

    def nearby(self, point: tuple[float, float, float], radius: float) -> list[dict]:
        found = [(box_distance(a, point), a) for a in self.visible()]
        close = sorted((f for f in found if f[0] <= radius), key=lambda f: f[0])
        return [{**a, "distance": round(d, 3)} for d, a in close]

    def apply(self, op: str, object_id: str | None, position: list[float] | None) -> dict:
        if op == "add":
            asset = self._add(position)
        else:
            asset = self.assets.get(object_id or "")
            if asset is None or asset["status"] == "removed":
                raise KeyError(object_id)
            if asset["mobility"] != "movable":
                raise ChangeError(f"{object_id} is {asset['mobility']}, so it can't change")
            if op == "move":
                self._move(asset, position)
            else:
                asset["status"] = "removed"
        change = {
            "change_id": len(self.changes) + 1,
            "op": op,
            "object_id": asset["object_id"],
            "position": position,
        }
        self.changes.append(change)
        return change

    def _add(self, position: list[float] | None) -> dict:
        if position is None:
            raise ChangeError("add needs a position")
        half = NEW_OBJECT_SIZE / 2
        object_id = (
            f"new-{sum(a['status'] == 'new, unconfirmed' for a in self.assets.values()) + 1:04d}"
        )
        asset = {
            "object_id": object_id,
            "label": "other",
            "label_confidence": 0.0,
            "center": list(position),
            "bbox_min": [c - half for c in position],
            "bbox_max": [c + half for c in position],
            "mapping": None,
            "mobility": "fixed",
            "status": "new, unconfirmed",
        }
        self.assets[object_id] = asset
        return asset

    @staticmethod
    def _move(asset: dict, position: list[float] | None) -> None:
        if position is None:
            raise ChangeError("move needs a position")
        shift = [p - c for p, c in zip(position, asset["center"], strict=True)]
        for key in ("center", "bbox_min", "bbox_max"):
            asset[key] = [v + s for v, s in zip(asset[key], shift, strict=True)]
