"""Backend API for the viewer and copilot.

The copilot needs the Excel pack in data/, and returns a marked placeholder without it.

make api                                      # fixture, on http://localhost:8001/docs
SCENE_ASSETS=path/to/assets.json make api     # real objects
"""

import math
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.api.copilot_link import ask, condition, details, load_engine
from app.api.db import open_database
from app.api.select_object import (
    NothingSelected,
    already_known,
    crop_selection,
    pick_object,
    suggest_config,
)
from app.api.store import ChangeError, SceneStore
from app.copilot.llm import load_writer
from app.nav.grid import NavGrid, load_grid
from app.nav.route import BODIES, NoRoute, placeholder_route, plan_route
from app.scene.load import Splats, read_splats

DEFAULT_ASSETS = Path("fixtures/sample_assets.json")
UNCONFIRMED_NEW = "new, unconfirmed"
Position = Annotated[list[float], Field(min_length=3, max_length=3)]


class PreviewMove(BaseModel):
    object_id: str
    position: Position
    yaw: float | None = None


class RouteRequest(BaseModel):
    start: Position
    object_id: str
    profile: Literal["robot", "person"] = "person"
    preview: PreviewMove | None = None


class ChangeRequest(BaseModel):
    op: Literal["add", "move", "rotate", "remove"]
    object_id: str | None = None
    position: Position | None = None
    yaw: float | None = None
    details: dict[str, Any] | None = None


class SelectionRequest(BaseModel):
    origin: Position
    corners: Annotated[list[Position], Field(min_length=4, max_length=4)]
    rectangle: Annotated[list[float], Field(min_length=4, max_length=4)]
    image: str | None = None


class CopilotRequest(BaseModel):
    question: str
    object_id: str | None = None


def shifted_box(
    asset: dict, position: list[float], yaw: float | None = None
) -> tuple[list[float], list[float]]:
    """Return an object's box as if its center were at `position`, optionally rotated."""
    target_yaw = asset.get("yaw", 0.0) if yaw is None else yaw
    if target_yaw:
        w, _, d = asset.get(
            "base_size",
            [
                abs(asset["bbox_max"][0] - asset["bbox_min"][0]),
                abs(asset["bbox_max"][1] - asset["bbox_min"][1]),
                abs(asset["bbox_max"][2] - asset["bbox_min"][2]),
            ],
        )
        hw, hd = w / 2, d / 2
        cos_y = abs(math.cos(target_yaw))
        sin_y = abs(math.sin(target_yaw))
        hw_rot = hw * cos_y + hd * sin_y
        hd_rot = hw * sin_y + hd * cos_y
        min_y = min(asset["bbox_min"][1], asset["bbox_max"][1])
        max_y = max(asset["bbox_min"][1], asset["bbox_max"][1])
        y_half = (max_y - min_y) / 2
        if asset["bbox_min"][1] <= asset["bbox_max"][1]:
            y_min, y_max = position[1] - y_half, position[1] + y_half
        else:
            y_min, y_max = position[1] + y_half, position[1] - y_half
        return (
            [round(position[0] - hw_rot, 3), round(y_min, 3), round(position[2] - hd_rot, 3)],
            [round(position[0] + hw_rot, 3), round(y_max, 3), round(position[2] + hd_rot, 3)],
        )
    shift = [p - c for p, c in zip(position, asset["center"], strict=True)]
    low = [round(v + d, 3) for v, d in zip(asset["bbox_min"], shift, strict=True)]
    high = [round(v + d, 3) for v, d in zip(asset["bbox_max"], shift, strict=True)]
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
                boxes.append(shifted_box(asset, preview.position, getattr(preview, "yaw", None)))
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
        if asset is None or asset["status"] == "removed":
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
        if grid is not None:
            try:
                found = plan_route(
                    grid,
                    tuple(request.start),
                    tuple(asset["bbox_min"]),
                    tuple(asset["bbox_max"]),
                    width=BODIES[request.profile][0],
                    band=BODIES[request.profile][1],
                    footprints=footprints(store, request.object_id, request.preview),
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

    @app.post("/api/changes")
    def change(request: ChangeRequest) -> dict:
        try:
            return store.apply(
                request.op,
                request.object_id,
                request.position,
                request.details,
                yaw=request.yaw,
            )
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

    @app.post("/api/changes/reset")
    def reset() -> dict:
        store.reset()
        return {"changes": store.changes}

    return app


app = create_app()
