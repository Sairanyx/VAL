"""Backend API for the viewer and copilot.

The copilot needs the Excel pack in data/, and returns a marked placeholder without it.

make api                                      # fixture, on http://localhost:8001/docs
SCENE_ASSETS=path/to/assets.json make api     # real objects
"""

import os
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.api.copilot_link import ask, condition, details, load_engine
from app.api.db import open_database
from app.api.store import ChangeError, SceneStore
from app.nav.grid import NavGrid, load_grid
from app.nav.route import BODIES, NoRoute, placeholder_route, plan_route

DEFAULT_ASSETS = Path("fixtures/sample_assets.json")
UNCONFIRMED_NEW = "new, unconfirmed"
Position = Annotated[list[float], Field(min_length=3, max_length=3)]


class RouteRequest(BaseModel):
    start: Position
    object_id: str
    profile: Literal["robot", "person"] = "person"


class ChangeRequest(BaseModel):
    op: Literal["add", "move", "remove"]
    object_id: str | None = None
    position: Position | None = None


class CopilotRequest(BaseModel):
    question: str
    object_id: str | None = None


def footprints(store: SceneStore, target_id: str) -> list[tuple[list[float], list[float]]]:
    """Return boxes that block routes on top of the map: movable and newly added objects."""
    return [
        (asset["bbox_min"], asset["bbox_max"])
        for asset in store.visible()
        if asset["object_id"] != target_id
        and (asset["mobility"] == "movable" or asset["status"] == UNCONFIRMED_NEW)
    ]


def create_app(
    assets_path: Path | str | None = None,
    grid: NavGrid | Path | str | None = None,
    engine=None,
    database=None,
) -> FastAPI:
    engine = engine or load_engine()
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
                    footprints=footprints(store, request.object_id),
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
            answer = ask(engine, store.visible(), request.question, request.object_id)
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
            return store.apply(request.op, request.object_id, request.position)
        except KeyError:
            raise HTTPException(404, f"No object {request.object_id}") from None
        except ChangeError as error:
            raise HTTPException(409, str(error)) from None

    @app.post("/api/changes/reset")
    def reset() -> dict:
        store.reset()
        return {"changes": store.changes}

    return app


app = create_app()
