"""Backend API for the viewer and copilot.

The copilot needs the Excel pack in data/, and returns a marked placeholder without it.

make api                                      # fixture, on http://localhost:8001/docs
SCENE_ASSETS=path/to/assets.json make api     # real objects
"""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.api.collisions import MoveCheck, check_move
from app.api.copilot_link import ask, condition, details, load_engine
from app.api.db import open_database
from app.api.select_object import (
    NothingSelected,
    already_known,
    crop_selection,
    pick_object,
    split_object,
    suggest_config,
)
from app.api.store import GONE, ChangeError, SceneStore
from app.copilot.llm import load_writer
from app.nav.grid import NavGrid, load_grid
from app.nav.route import BODIES, NoRoute, placeholder_route, plan_route
from app.scene.load import Splats, read_splats, write_splats
from app.scene.split_movable import FLOOR_MARGIN, split_movable

DEFAULT_ASSETS = Path("fixtures/sample_assets.json")
UNCONFIRMED_NEW = "new, unconfirmed"
Position = Annotated[list[float], Field(min_length=3, max_length=3)]


class PreviewMove(BaseModel):
    object_id: str
    position: Position


class RouteRequest(BaseModel):
    start: Position
    object_id: str
    profile: Literal["robot", "person"] = "person"
    preview: PreviewMove | None = None


class ChangeRequest(BaseModel):
    op: Literal["add", "move", "remove", "split", "combine"]
    object_id: str | None = None
    position: Position | None = None
    details: dict[str, Any] | None = None


class SuggestRequest(BaseModel):
    image: str
    rectangle: Annotated[list[float], Field(min_length=4, max_length=4)]


class MoveCheckRequest(BaseModel):
    position: Position


class SelectionRequest(BaseModel):
    origin: Position
    corners: Annotated[list[Position], Field(min_length=4, max_length=4)]
    rectangle: Annotated[list[float], Field(min_length=4, max_length=4)]
    image: str | None = None


class CopilotRequest(BaseModel):
    question: str
    object_id: str | None = None


def shifted_box(asset: dict, position: list[float]) -> tuple[list[float], list[float]]:
    """Return an object's box as if its center were at `position`."""
    shift = [p - c for p, c in zip(position, asset["center"], strict=True)]
    low = [v + d for v, d in zip(asset["bbox_min"], shift, strict=True)]
    high = [v + d for v, d in zip(asset["bbox_max"], shift, strict=True)]
    return low, high


def footprints(
    store: SceneStore, target_id: str, preview: "PreviewMove | None" = None
) -> list[tuple[list[float], list[float]]]:
    """Return boxes that block routes on top of the map: movable and newly added objects.

    `preview` shows where an object is being dragged to, before the move is saved.
    """
    boxes = []
    for asset in store.visible():
        if asset["object_id"] == target_id:
            continue
        if asset["mobility"] == "movable" or asset["status"] == UNCONFIRMED_NEW:
            if preview and asset["object_id"] == preview.object_id:
                boxes.append(shifted_box(asset, preview.position))
            else:
                boxes.append((asset["bbox_min"], asset["bbox_max"]))
    return boxes


def create_app(
    assets_path: Path | str | None = None,
    grid: NavGrid | Path | str | None = None,
    engine=None,
    database=None,
) -> FastAPI:
    engine = engine or load_engine()
    writer = load_writer() if engine else None
    database = database or open_database()
    store = SceneStore(Path(assets_path or os.getenv("SCENE_ASSETS", DEFAULT_ASSETS)), database)
    grid = grid or os.getenv("SCENE_GRID")
    if isinstance(grid, str | Path):
        grid = load_grid(Path(grid))
    app = FastAPI(title="Field-service copilot API")
    # The viewer is served from another port on the local network.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    def require(object_id: str) -> dict:
        asset = store.get(object_id)
        if asset is None or asset["status"] in GONE:
            raise HTTPException(404, f"No object {object_id}")
        return asset

    def with_condition(asset: dict) -> dict:
        return {**asset, "condition": condition(asset, engine.store) if engine else None}

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/docs")

    @app.get("/api/health")
    def health() -> dict:
        return {
            "database": database.ping() if database else False,
            "unsaved_changes": len(store.unsaved),
            "copilot": engine is not None,
            "floor_map": grid is not None,
            "objects": len(store.visible()),
        }

    @app.get("/api/assets")
    def list_assets() -> dict:
        return {
            "scene_id": store.scene.get("scene_id"),
            "floor_y": store.scene.get("floor_y"),
            "start": store.scene.get("start"),
            "assets": [with_condition(asset) for asset in store.visible()],
        }

    @app.get("/api/assets/{object_id}")
    def get_asset(object_id: str) -> dict:
        asset = with_condition(require(object_id))
        if engine:
            found = {**asset, **details(asset, engine.store)}
            asset_id = (asset.get("mapping") or {}).get("asset_id")
            stored = database.telemetry(asset_id) if database and asset_id else None
            if stored:
                found["telemetry"] = stored
            return found
        return {**asset, "telemetry": [], "events": [], "maintenance": [], "documents": []}

    @app.get("/api/nearby")
    def nearby(
        x: float, y: float, z: float, radius: Annotated[float, Query(gt=0, le=100)] = 3.0
    ) -> dict:
        return {"assets": [with_condition(a) for a in store.nearby((x, y, z), radius)]}

    @app.post("/api/route")
    def route(request: RouteRequest) -> dict:
        asset = require(request.object_id)
        preview = request.preview
        low, high = asset["bbox_min"], asset["bbox_max"]
        if preview and preview.object_id == request.object_id:
            low, high = shifted_box(asset, preview.position)
        if grid is not None:
            try:
                found = plan_route(
                    grid,
                    tuple(request.start),
                    tuple(low),
                    tuple(high),
                    width=BODIES[request.profile][0],
                    band=BODIES[request.profile][1],
                    footprints=footprints(store, request.object_id, preview),
                )
            except NoRoute as reason:
                raise HTTPException(409, str(reason)) from None
            return {
                "path": found.path,
                "length": round(found.length, 3),
                "stop_distance": round(found.stop_distance, 3),
                "view_from": list(found.view_from),
                "profile": request.profile,
                "width": BODIES[request.profile][0],
                "placeholder": False,
            }
        floor_y = store.scene.get("floor_y", request.start[1])
        path, length = placeholder_route(tuple(request.start), tuple(asset["center"]), floor_y)
        return {
            "path": path,
            "length": round(length, 3),
            "profile": request.profile,
            "width": BODIES[request.profile][0],
            "placeholder": True,
        }

    @app.post("/api/copilot/query")
    def copilot(request: CopilotRequest) -> dict:
        if request.object_id:
            require(request.object_id)
        if engine:
            answer = ask(engine, store.visible(), request.question, request.object_id, writer)
            return {**answer, "placeholder": False}
        return {
            "answer": "The copilot isn't connected yet.",
            "observations": [],
            "hypotheses": [],
            "citations": [],
            "confidence": 0.0,
            "actions": [],
            "placeholder": True,
        }

    @app.get("/api/changes")
    def list_changes() -> dict:
        return {"changes": store.changes}

    def move_check(object_id: str, position: list[float]) -> MoveCheck:
        return check_move(
            require(object_id), position, store.visible(), grid, store.original(object_id)
        )

    @app.post("/api/objects/{object_id}/check-move")
    def check_a_move(object_id: str, request: MoveCheckRequest) -> dict:
        """Say whether an object can stand here, for the viewer to show while dragging."""
        result = move_check(object_id, request.position)
        return {"ok": result.ok, "reason": result.reason, "blockers": result.blockers}

    @app.post("/api/changes")
    def change(request: ChangeRequest) -> dict:
        # Checked here too, so that nothing can save a bad spot. Saved changes aren't rechecked on
        # restart, because the room they were made in may have changed since.
        if request.op == "move" and request.object_id and request.position:
            asset = store.get(request.object_id)
            if asset and asset.get("mobility") == "movable" and asset["status"] not in GONE:
                result = move_check(request.object_id, request.position)
                if not result.ok:
                    raise HTTPException(409, result.reason)
        try:
            return store.apply(request.op, request.object_id, request.position, request.details)
        except KeyError:
            raise HTTPException(404, f"No object {request.object_id}") from None
        except ChangeError as error:
            raise HTTPException(409, str(error)) from None

    scene_splats: list[Splats] = []

    def splats_for_selection() -> Splats:
        """Read the scene once, when first needed. It holds every splat's position."""
        if not scene_splats:
            path = os.getenv("SCENE_PLY")
            if not path or not Path(path).exists():
                raise HTTPException(503, "Selecting needs the scene: set SCENE_PLY to its file.")
            scene_splats.append(read_splats(Path(path)))
        return scene_splats[0]

    piece_files = Path(tempfile.mkdtemp(prefix="object-pieces-"))

    @app.get("/api/objects/{object_id}/home")
    def object_home(object_id: str) -> dict:
        """Say where an object's splats are in the scan, to hide them there when it's moved."""
        require(object_id)
        return {**store.home_box(object_id), "floor_margin": FLOOR_MARGIN}

    @app.get("/api/objects/{object_id}/splats.ply")
    def object_splats(object_id: str) -> FileResponse:
        """Cut an object's splats out of the scan, for moving the real thing."""
        require(object_id)
        path = piece_files / f"{hashlib.sha256(object_id.encode()).hexdigest()}.ply"
        if not path.exists():
            splats = splats_for_selection()
            home = store.home_box(object_id)
            up = np.asarray(store.scene.get("up") or (0.0, -1.0, 0.0), dtype=np.float64)
            axis = int(np.argmax(np.abs(up)))
            floor_height = store.scene.get("floor_y", 0.0) * float(up[axis])
            _, pieces = split_movable(splats, [{**home, "object_id": object_id}], floor_height, up)
            write_splats(pieces[object_id], path)
        return FileResponse(path, media_type="application/octet-stream")

    @app.post("/api/objects/propose")
    def propose(request: SelectionRequest) -> dict:
        """Measure a selected object and suggest its settings. Nothing is saved until confirmed."""
        splats = splats_for_selection()
        floor_y = store.scene.get("floor_y", 0.0)
        try:
            box = pick_object(splats, request.origin, request.corners, floor_y)
        except NothingSelected as reason:
            raise HTTPException(422, str(reason)) from None
        crop = None
        if writer is not None and request.image:
            crop = crop_selection(request.image, request.rectangle)
        tags = [a["mapping"]["tag"] for a in store.visible() if (a.get("mapping") or {}).get("tag")]
        return {
            **box,
            **suggest_config(writer, crop, tags),
            "already_known": already_known(box, store.visible()),
        }

    def linked_tags() -> list[str]:
        return [a["mapping"]["tag"] for a in store.visible() if (a.get("mapping") or {}).get("tag")]

    @app.post("/api/objects/{object_id}/split/propose")
    def propose_split(object_id: str, request: SelectionRequest) -> dict:
        """Measure the selected part of an object and the rest. Nothing is saved until confirmed."""
        parent = require(object_id)
        splats = splats_for_selection()
        floor_y = store.scene.get("floor_y", 0.0)
        try:
            part, rest = split_object(splats, parent, request.origin, request.corners, floor_y)
        except NothingSelected as reason:
            raise HTTPException(422, str(reason)) from None
        crop = None
        if writer is not None and request.image:
            crop = crop_selection(request.image, request.rectangle)
        return {
            "part": {**part, **suggest_config(writer, crop, linked_tags())},
            "rest": {**rest, **suggest_config(None, None, [])},
            "linked": (parent.get("mapping") or {}).get("tag"),
        }

    @app.post("/api/objects/suggest")
    def suggest(request: SuggestRequest) -> dict:
        """Suggest settings for part of a viewer screenshot."""
        crop = crop_selection(request.image, request.rectangle) if writer is not None else None
        return suggest_config(writer, crop, linked_tags())

    @app.post("/api/changes/reset")
    def reset() -> dict:
        store.reset()
        return {"changes": store.changes}

    return app


app = create_app()
