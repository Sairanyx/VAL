"""Scene objects and the change log. In memory for now, with the same interface for a database."""

import copy
import json
import math
from pathlib import Path

NEW_OBJECT_SIZE = 0.5
GONE = {"removed", "split", "combined"}
COMBINE_FIELDS = {"label", "label_source", "mobility", "mobility_reason"}
OPERATOR_FIELDS = {
    "bbox_min",
    "bbox_max",
    "label",
    "label_confidence",
    "label_source",
    "mobility",
    "mobility_reason",
    "reason",
    "visible_text",
    "possible_tag",
}


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
    def __init__(self, path: Path, database=None):
        self.path = Path(path)
        self.scene = json.loads(self.path.read_text())
        self.database = database
        self.unsaved: list[dict] = []
        self.scene_id = str(self.scene.get("scene_id", self.path.stem))
        self._restore_base()
        if database:
            for change in database.load_changes(self.scene_id):
                self._apply(
                    change["op"], change["object_id"], change["position"], change.get("details")
                )

    def reset(self) -> None:
        """Restore the base scan's objects and forget saved changes. The file isn't overwritten."""
        self._restore_base()
        self.unsaved = []
        if self.database:
            self.database.clear_changes(self.scene_id)

    def _restore_base(self) -> None:
        self.assets = {a["object_id"]: copy.deepcopy(a) for a in self.scene["assets"]}
        for asset in self.assets.values():
            asset.setdefault("mobility", "unsure")
            asset.setdefault("status", "detected")
        self.changes: list[dict] = []

    def original(self, object_id: str) -> dict | None:
        """Return an object's record from the scan, before any moves. New objects have none."""
        return next((a for a in self.scene["assets"] if a["object_id"] == object_id), None)

    def visible(self) -> list[dict]:
        return [a for a in self.assets.values() if a["status"] not in GONE]

    def get(self, object_id: str) -> dict | None:
        return self.assets.get(object_id)

    def nearby(self, point: tuple[float, float, float], radius: float) -> list[dict]:
        found = [(box_distance(a, point), a) for a in self.visible()]
        close = sorted((f for f in found if f[0] <= radius), key=lambda f: f[0])
        return [{**a, "distance": round(d, 3)} for d, a in close]

    def apply(
        self,
        op: str,
        object_id: str | None,
        position: list[float] | None,
        details: dict | None = None,
    ) -> dict:
        change = self._apply(op, object_id, position, details)
        if self.database:
            self.unsaved.append(change)
            self.save_pending()
        return {**change, "saved": not self.unsaved} if self.database else change

    def save_pending(self) -> None:
        """Save changes in order, keeping any the database can't take yet for the next try."""
        while self.unsaved and self.database.save_change(self.scene_id, self.unsaved[0]):
            self.unsaved.pop(0)

    def _apply(
        self,
        op: str,
        object_id: str | None,
        position: list[float] | None,
        details: dict | None = None,
    ) -> dict:
        parts: list[str] = []
        if op == "add":
            asset = self._add(position, details)
        elif op == "split":
            asset = self.assets.get(object_id or "")
            if asset is None or asset["status"] in GONE:
                raise KeyError(object_id)
            parts = self._split(asset, details)
        elif op == "combine":
            asset = self.assets.get(object_id or "")
            if asset is None or asset["status"] in GONE:
                raise KeyError(object_id)
            parts = [self._combine(asset, details)]
        else:
            asset = self.assets.get(object_id or "")
            if asset is None or asset["status"] in GONE:
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
        if details:
            change["details"] = details
        if parts:
            change["parts"] = parts
        self.changes.append(change)
        return change

    def _add(self, position: list[float] | None, details: dict | None = None) -> dict:
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
        if details:
            # Only what an operator may set: identity and status never come from this.
            asset.update({k: v for k, v in details.items() if k in OPERATOR_FIELDS})
            asset["label_grade"] = "operator_added"
        self.assets[object_id] = asset
        return asset

    def _split(self, parent: dict, details: dict | None) -> list[str]:
        """Replace an object with its parts. Its record link isn't guessed onto either of them."""
        parts = (details or {}).get("parts") or []
        if len(parts) != 2:
            raise ChangeError("split needs two parts")
        if parent.get("mapping"):
            raise ChangeError(
                f"{parent['object_id']} is linked to {parent['mapping'].get('tag')}, "
                "so splitting it would lose that link"
            )
        ids = []
        for number, part in enumerate(parts, start=1):
            object_id = f"{parent['object_id']}.{number}"
            low, high = part["bbox_min"], part["bbox_max"]
            asset = {
                "object_id": object_id,
                "label": "other",
                "label_confidence": 0.0,
                "center": [(a + b) / 2 for a, b in zip(low, high, strict=True)],
                "mapping": None,
                "mobility": "unsure",
                "status": "new, unconfirmed",
                "split_from": parent["object_id"],
            }
            asset.update({k: v for k, v in part.items() if k in OPERATOR_FIELDS})
            asset["label_grade"] = "operator_added"
            self.assets[object_id] = asset
            ids.append(object_id)
        parent["status"] = "split"
        return ids

    def _combine(self, first: dict, details: dict | None) -> str:
        """Replace two objects with one around both. Record links aren't merged or guessed."""
        other_id = (details or {}).get("other")
        other = self.assets.get(other_id or "")
        if other is None or other["status"] in GONE:
            raise KeyError(other_id)
        if other is first:
            raise ChangeError("Choose a different object to combine with")
        for asset in (first, other):
            if asset.get("mapping"):
                raise ChangeError(
                    f"{asset['object_id']} is linked to {asset['mapping'].get('tag')}, "
                    "so combining it would lose that link"
                )
        low = [min(a, b) for a, b in zip(first["bbox_min"], other["bbox_min"], strict=True)]
        high = [max(a, b) for a, b in zip(first["bbox_max"], other["bbox_max"], strict=True)]
        object_id = f"{first['object_id']}+{other['object_id']}"
        asset = {
            "object_id": object_id,
            "label": first.get("label", "other"),
            "label_confidence": 0.0,
            "center": [(a + b) / 2 for a, b in zip(low, high, strict=True)],
            "bbox_min": low,
            "bbox_max": high,
            "mapping": None,
            "mobility": "unsure",
            "status": "new, unconfirmed",
            "combined_from": [first["object_id"], other["object_id"]],
        }
        asset.update({k: v for k, v in (details or {}).items() if k in COMBINE_FIELDS})
        asset["label_grade"] = "operator_added"
        self.assets[object_id] = asset
        first["status"] = other["status"] = "combined"
        return object_id

    @staticmethod
    def _move(asset: dict, position: list[float] | None) -> None:
        if position is None:
            raise ChangeError("move needs a position")
        shift = [p - c for p, c in zip(position, asset["center"], strict=True)]
        for key in ("center", "bbox_min", "bbox_max"):
            asset[key] = [v + s for v, s in zip(asset[key], shift, strict=True)]
