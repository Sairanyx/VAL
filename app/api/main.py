"""Backend API for the viewer and copilot.

The copilot needs the Excel pack in data/, and returns a marked placeholder without it.

make api                                      # fixture, on http://localhost:8001/docs
SCENE_ASSETS=path/to/assets.json make api     # real objects
"""

import base64
import hashlib
import io
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from app.api.collisions import MoveCheck, check_move
from app.api.commands import ACTIONS, CommandQueue, problem_with
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
from app.bim.ifc import ifc_text
from app.bim.model import build_model
from app.copilot.llm import can_reword, load_writer, warm_up
from app.copilot.voice import MAX_AUDIO_BYTES, TRANSCRIBER
from app.nav.grid import NavGrid, largest_region, load_grid
from app.nav.route import (
    BODIES,
    NoRoute,
    clearance_with_footprints,
    placeholder_route,
    plan_route,
)
from app.plan.export_dxf import write_dxf
from app.plan.layout import build_layout
from app.scene.load import Splats, read_splats, write_splats
from app.scene.split_movable import FLOOR_MARGIN, split_movable

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
    op: Literal["add", "move", "rotate", "remove", "split", "combine", "duplicate", "rename"]
    object_id: str | None = None
    position: Position | None = None
    yaw: float | None = None
    details: dict[str, Any] | None = None


class SuggestRequest(BaseModel):
    image: str
    rectangle: Annotated[list[float], Field(min_length=4, max_length=4)]


class ViewerCommand(BaseModel):
    action: str
    args: dict[str, Any] = Field(default_factory=dict)


class CommandResult(BaseModel):
    ok: bool
    message: str = ""


class MoveCheckRequest(BaseModel):
    position: Position
    yaw: float | None = None


class SelectionRequest(BaseModel):
    origin: Position
    corners: Annotated[list[Position], Field(min_length=4, max_length=4)]
    rectangle: Annotated[list[float], Field(min_length=4, max_length=4)]
    image: str | None = None


class CopilotRequest(BaseModel):
    question: str
    object_id: str | None = None
    quick: bool = False  # answer at once from the records, without the language model


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
    # Objects whose info was removed but which are still in the scan stay in the way. Fixed ones
    # are already part of the permanent map.
    for asset in store.assets.values():
        if asset["status"] == "removed" and asset.get("splats_kept"):
            if asset["mobility"] == "movable" and asset["object_id"] != target_id:
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
    TRANSCRIBER.warm_up()
    if engine:
        warm_up(engine, writer)
    database = database or open_database()
    store = SceneStore(Path(assets_path or os.getenv("SCENE_ASSETS", DEFAULT_ASSETS)), database)
    grid = grid or os.getenv("SCENE_GRID")
    if isinstance(grid, str | Path):
        grid = load_grid(Path(grid))
    app = FastAPI(title="Val field-service API")
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

    commands = CommandQueue()

    @app.get("/api/viewer/actions")
    def viewer_actions() -> dict:
        """List what the viewer can be told to do, and what each action needs."""
        return {"actions": ACTIONS}

    @app.post("/api/viewer/commands")
    def send_command(request: ViewerCommand) -> dict:
        """Tell the open viewer to do something. Check the command by ID for its result."""
        problem = problem_with(request.action, request.args)
        if problem:
            raise HTTPException(422, problem)
        return commands.add(request.action, request.args)

    @app.get("/api/viewer/commands")
    def poll_commands(after: int | None = None) -> dict:
        """Commands newer than `after`. Without it, only the latest ID, so old ones don't rerun."""
        found = [] if after is None else commands.after(after)
        return {"last_id": commands.last_id, "commands": found}

    @app.get("/api/viewer/commands/{command_id}")
    def get_command(command_id: int) -> dict:
        command = commands.get(command_id)
        if command is None:
            raise HTTPException(404, f"No command {command_id}")
        return command

    @app.post("/api/viewer/commands/{command_id}/result")
    def report_result(command_id: int, result: CommandResult) -> dict:
        command = commands.get(command_id)
        if command is None:
            raise HTTPException(404, f"No command {command_id}")
        command["result"] = result.model_dump()
        return command

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
                "changes": len(store.changes),
            }
        floor_y = store.scene.get("floor_y", request.start[1])
        path, length = placeholder_route(tuple(request.start), tuple(asset["center"]), floor_y)
        return {
            "path": path,
            "length": round(length, 3),
            "profile": request.profile,
            "width": BODIES[request.profile][0],
            "placeholder": True,
            "changes": len(store.changes),
        }

    @app.post("/api/copilot/transcribe")
    async def transcribe(request: Request) -> dict:
        """Turn recorded speech into text on this machine. The audio isn't kept."""
        if not TRANSCRIBER.installed:
            raise HTTPException(503, "Speech isn't installed. Run this once: make voice-model")
        audio = await request.body()
        if not audio:
            raise HTTPException(400, "No audio was received.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "That recording is too long.")
        tags = {asset.tag for asset in engine.store.list_assets()} if engine else set()
        try:
            return await run_in_threadpool(TRANSCRIBER.transcribe, audio, tags)
        except Exception as error:
            raise HTTPException(422, f"Couldn't read that recording: {error}") from error

    @app.post("/api/copilot/query")
    def copilot(request: CopilotRequest) -> dict:
        if request.object_id:
            require(request.object_id)
        if engine:
            model = None if request.quick else writer
            answer = ask(engine, store.visible(), request.question, request.object_id, model)
            better = bool(request.quick and writer) and can_reword(engine, answer, request.question)
            return {**answer, "placeholder": False, "can_reword": better}
        return {
            "answer": "Val isn't connected yet: the plant records aren't loaded.",
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

    def move_check(object_id: str, position: list[float], yaw: float | None = None) -> MoveCheck:
        asset = require(object_id)
        # Check the box at the new angle, so turning can't push an object into another.
        low, high = shifted_box(asset, asset["center"], yaw)
        turned = {**asset, "bbox_min": low, "bbox_max": high}
        return check_move(turned, position, store.visible(), grid, store.original(object_id))

    @app.post("/api/objects/{object_id}/check-move")
    def check_a_move(object_id: str, request: MoveCheckRequest) -> dict:
        """Say whether an object can stand here, for the viewer to show while dragging."""
        result = move_check(object_id, request.position, request.yaw)
        return {"ok": result.ok, "reason": result.reason, "blockers": result.blockers}

    @app.post("/api/changes")
    def change(request: ChangeRequest) -> dict:
        # Checked here too, so that nothing can save a bad spot. Saved changes aren't rechecked on
        # restart, because the room they were made in may have changed since.
        if request.op in ("move", "rotate") and request.object_id:
            asset = store.get(request.object_id)
            if asset and asset.get("mobility") == "movable" and asset["status"] not in GONE:
                position = request.position or asset["center"]
                result = move_check(request.object_id, position, request.yaw)
                if not result.ok:
                    raise HTTPException(409, result.reason)
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
                raise HTTPException(503, "This needs the scene: set SCENE_PLY to its file.")
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
        if store.has_moved(parent):
            message = f"{object_id} has been moved. Undo that, then split it"
            raise HTTPException(409, message)
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

    plan_cache: dict[str, Any] = {}

    def plan_layout() -> dict[str, Any]:
        """Build the floor layout once, when first needed. It takes under a second."""
        if not plan_cache:
            up = tuple(store.scene.get("up") or (0.0, -1.0, 0.0))
            floor_y = store.scene.get("floor_y", 0.0)
            try:
                image, description = build_layout(splats_for_selection(), floor_y, up)
            except ValueError as error:
                raise HTTPException(503, f"Couldn't work out the room: {error}") from error
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            plan_cache.update(png=buffer.getvalue(), description=description, up=up)
        return plan_cache

    @app.get("/api/plan")
    def plan() -> dict:
        """Describe the floor layout: its extent, and the room estimated from the scan."""
        return plan_layout()["description"]

    @app.get("/api/plan/floor.png")
    def plan_image() -> Response:
        return Response(plan_layout()["png"], media_type="image/png")

    @app.get("/api/plan/walkable")
    def plan_walkable(profile: Literal["robot", "person"] = "person") -> dict:
        """Where a body can walk right now, as a mask over the floor map. Walk mode keeps to it.

        The same map, body width, and moved objects' footprints as routing, so walking and routes
        agree. The mask is packed bits, row by row, over `shape`.
        """
        if grid is None:
            raise HTTPException(404, "No floor map is loaded")
        width, band = BODIES[profile]
        clearance = clearance_with_footprints(grid, footprints(store, ""), band)
        walk = largest_region(clearance >= width / 2)
        return {
            "origin": [float(v) for v in grid.origin],
            "cell": float(grid.cell),
            "axes": [int(a) for a in grid.axes],
            "shape": [int(n) for n in walk.shape],
            "mask": base64.b64encode(np.packbits(walk, axis=None).tobytes()).decode(),
            "changes": len(store.changes),
        }

    @app.get("/api/plan/layout.dxf")
    def plan_dxf() -> Response:
        """Return the layout for CAD tools, with objects where they stand now."""
        layout = plan_layout()
        text = write_dxf(
            layout["description"], store.visible(), store.scene.get("fault_tag"), layout["up"]
        )
        headers = {"Content-Disposition": 'attachment; filename="floor_layout.dxf"'}
        return Response(text, media_type="application/dxf", headers=headers)

    def shapes_where_they_stand() -> dict[str, dict]:
        """Return the fitted shapes of objects still in the room, moved along with them."""
        path = store.path.with_name("shapes.json")
        shapes = json.loads(path.read_text()) if path.exists() else {}
        placed = {}
        for asset in store.visible():
            object_id = asset["object_id"]
            source = asset.get("duplicated_from") or object_id
            if source in shapes:
                shift = np.subtract(asset["center"], store.home_box(source)["center"])
                center = np.add(shapes[source]["center"], shift).tolist()
                placed[object_id] = {**shapes[source], "center": center}
        return placed

    @app.get("/api/plan/model.ifc")
    def plan_ifc() -> Response:
        """Return the BIM model for BIM tools, with objects as they stand now."""
        document = {**store.scene, "scene_id": store.scene_id, "assets": store.visible()}
        room = plan_layout()["description"]["room"]
        model = build_model(document, shapes_where_they_stand(), room)
        headers = {"Content-Disposition": 'attachment; filename="model.ifc"'}
        return Response(ifc_text(model), media_type="application/x-step", headers=headers)

    @app.post("/api/changes/undo")
    def undo() -> dict:
        """Take back only the latest change. Reset takes back all of them."""
        undone = store.undo_last()
        if undone is None:
            raise HTTPException(409, "Nothing to undo")
        return {"undone": undone, "changes": store.changes}

    @app.post("/api/changes/reset")
    def reset() -> dict:
        store.reset()
        return {"changes": store.changes}

    return app


app = create_app()
