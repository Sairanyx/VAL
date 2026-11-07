"""Backend API for the viewer and copilot. The copilot answer is a placeholder for now.

make api                                      # fixture, on http://localhost:8001/docs
SCENE_ASSETS=path/to/assets.json make api     # real objects
"""

import os
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.api.store import ChangeError, SceneStore
from app.nav.route import FloorMap, NoRoute, placeholder_route, plan_route

DEFAULT_ASSETS = Path("fixtures/sample_assets.json")
Position = Annotated[list[float], Field(min_length=3, max_length=3)]
DEFAULT_FLOOR = Path("data/scene/equipment_room/nav_grid.npz")


class RouteRequest(BaseModel):
    start: Position
    object_id: str
    profile: Literal["robot", "person", "carrying"] = "person"


class ChangeRequest(BaseModel):
    op: Literal["add", "move", "remove"]
    object_id: str | None = None
    position: Position | None = None


class CopilotRequest(BaseModel):
    question: str
    object_id: str | None = None


def create_app(
    assets_path: Path | str | None = None, floor_path: Path | str | None = None
) -> FastAPI:
    store = SceneStore(Path(assets_path or os.getenv("SCENE_ASSETS", DEFAULT_ASSETS)))
    floor_file = Path(floor_path or os.getenv("NAV_GRID", DEFAULT_FLOOR))
    # Without a floor map, the viewer still gets a marked placeholder route.
    floor = FloorMap.load(floor_file) if floor_file.exists() else None
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

    @app.get("/api/assets")
    def list_assets() -> dict:
        return {
            "scene_id": store.scene.get("scene_id"),
            "floor_y": store.scene.get("floor_y"),
            "start": store.scene.get("start"),
            "assets": store.visible(),
        }

    @app.get("/api/assets/{object_id}")
    def get_asset(object_id: str) -> dict:
        # Hannu's data store fills these lists.
        return {**require(object_id), "telemetry": [], "events": [], "documents": []}

    @app.get("/api/nearby")
    def nearby(
        x: float, y: float, z: float, radius: Annotated[float, Query(gt=0, le=100)] = 3.0
    ) -> dict:
        return {"assets": store.nearby((x, y, z), radius)}

    @app.post("/api/route")
    def route(request: RouteRequest) -> dict:
        asset = require(request.object_id)
        if floor is not None:
            try:
                return plan_route(
                    floor, request.start, asset["bbox_min"], asset["bbox_max"], request.profile
                )
            except NoRoute as error:
                raise HTTPException(409, str(error)) from None
        floor_y = store.scene.get("floor_y", request.start[1])
        path, length = placeholder_route(tuple(request.start), tuple(asset["center"]), floor_y)
        return {
            "path": path,
            "length": round(length, 3),
            "profile": request.profile,
            "placeholder": True,
        }

    @app.post("/api/copilot/query")
    def copilot(request: CopilotRequest) -> dict:
        if request.object_id:
            require(request.object_id)
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
