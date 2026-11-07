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
import re
import tempfile
import threading
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
    in_box,
    pick_object,
    split_object,
    suggest_config,
)
from app.api.store import GONE, ChangeError, SceneStore
from app.bim.ifc import ifc_text
from app.bim.model import build_model
from app.copilot.llm import can_reword, load_writer, warm_up
from app.copilot.voice import MAX_AUDIO_BYTES, TRANSCRIBER
from app.dashboard import render_dashboard
from app.nav.grid import NavGrid, largest_region, load_grid, open_boxes, vacate
from app.nav.route import (
    BODIES,
    NoRoute,
    best_view,
    clearance_with_footprints,
    placeholder_route,
    plan_route,
)
from app.plan.export_dxf import write_dxf
from app.plan.layout import build_layout
from app.scene.cover import cover_boxes
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


def ifc_file_name(asset: dict) -> str:
    """Name a one-object IFC file after its record tag, given name, or ID, safe for any system."""
    tag = (asset.get("mapping") or {}).get("tag")
    text = tag or asset.get("name") or asset["object_id"]
    return f"{re.sub(r'[^A-Za-z0-9._-]+', '_', text).strip('_.') or asset['object_id']}.ifc"


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

    dashboards: dict[tuple, bytes] = {}

    @app.get("/api/assets/{object_id}/dashboard.png")
    def asset_dashboard(object_id: str) -> Response:
        """Charts of the Excel record linked to an object: health, telemetry, events, service."""
        asset = require(object_id)
        link = asset.get("mapping") or {}
        if not engine or not link.get("asset_id"):
            raise HTTPException(404, f"{object_id} has no linked record, so there's no dashboard")
        key = (object_id, link["asset_id"], link.get("method"), link.get("confidence"))
        if key not in dashboards:
            try:
                dashboards[key] = render_dashboard(
                    engine.store, link["asset_id"], {**link, "object_id": object_id}
                )
            except KeyError as error:
                raise HTTPException(404, f"No record {link['asset_id']} in the data") from error
        return Response(dashboards[key], media_type="image/png")

    @app.get("/api/nearby")
    def nearby(
        x: float, y: float, z: float, radius: Annotated[float, Query(gt=0, le=100)] = 3.0
    ) -> dict:
        return {"assets": [with_condition(a) for a in store.nearby((x, y, z), radius)]}

    opened_maps: dict[tuple[str, ...], NavGrid] = {}

    def floor_map(also_left: str | None = None) -> NavGrid | None:
        """Return the floor map with the spots that objects have left open again.

        Route, best view, walkable floor and move checks all use this one, so they agree.
        - Moved objects: their old box opens where only splats that went with them blocked it.
          That needs the scene file, or their old spot stays blocked as before.
        - Deleted objects whose splats were hidden: their whole box opens, as the scan never saw
          the floor under them. "Remove info" keeps them in the scan, so they still block.
        `also_left` is an object being dragged, before it's saved. Undo and Reset close it again.
        """
        if grid is None:
            return None
        moved = {
            asset["object_id"]
            for asset in store.assets.values()
            if asset["status"] not in GONE and store.has_moved(asset)
        }
        if also_left:
            moved.add(also_left)
        deleted = {
            asset["object_id"]
            for asset in store.assets.values()
            if asset["status"] == "removed" and not asset.get("splats_kept")
        }
        key = (tuple(sorted(moved)), tuple(sorted(deleted - moved)))
        if not key[0] and not key[1]:
            return grid
        if key not in opened_maps:
            opened = grid
            if key[0]:
                try:
                    splats = splats_for_selection()
                except HTTPException:
                    splats = None
                if splats is not None:
                    own = left_splats(key[0], splats.positions)
                    boxes = [home_corners(object_id) for object_id in key[0]]
                    opened = vacate(opened, splats.positions, splats.opacities, own, boxes)
            if key[1]:
                opened = open_boxes(opened, [home_corners(object_id) for object_id in key[1]])
            opened_maps.clear()  # One state at a time: changes come one after another.
            opened_maps[key] = opened
        return opened_maps[key]

    def home_corners(object_id: str) -> tuple[list[float], list[float]]:
        home = store.home_box(object_id)
        return home["bbox_min"], home["bbox_max"]

    @app.get("/api/objects/{object_id}/view")
    def object_view(object_id: str) -> dict:
        """Return where to stand to see an object. Null without a floor map."""
        asset = require(object_id)
        view = None
        if grid is not None:
            view = best_view(
                floor_map(),
                tuple(asset["bbox_min"]),
                tuple(asset["bbox_max"]),
                footprints(store, object_id),
            )
        if view is None:
            return {"from": None, "clear": False}
        return {"from": list(view.point), "clear": view.clear}

    @app.post("/api/route")
    def route(request: RouteRequest) -> dict:
        asset = require(request.object_id)
        if grid is not None:
            try:
                found = plan_route(
                    floor_map(request.preview.object_id if request.preview else None),
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
        # Checked at the new angle, so turning can't push an object into another. Its own old spot
        # counts as open, so it can go back, and so can something else.
        original = store.original(object_id)
        return check_move(asset, position, store.visible(), floor_map(object_id), original, yaw)

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
    reading = threading.Lock()

    def splats_for_selection() -> Splats:
        """Read the scene once, when first needed. It holds every splat's position."""
        with reading:  # Requests and the warm-up below mustn't read it twice.
            if not scene_splats:
                path = os.getenv("SCENE_PLY")
                if not path or not Path(path).exists():
                    raise HTTPException(503, "This needs the scene: set SCENE_PLY to its file.")
                scene_splats.append(read_splats(Path(path)))
        return scene_splats[0]

    def left_splats(object_ids: tuple[str, ...], positions: np.ndarray) -> np.ndarray:
        """Return the splats that went with these objects: everything in each one's old box, as
        the viewer hides that box when it moves, except splats labelled as another object."""
        members_of({"object_id": object_ids[0]})  # loads the labels
        labels = scan_members["labels"]
        labelled = labels is not None and len(labels) == len(positions)
        left = np.zeros(len(positions), dtype=bool)
        for object_id in object_ids:
            asset = store.get(object_id)
            inside = in_box(positions, store.home_box(object_id))
            if labelled:
                parts = asset.get("combined_from") or [object_id]
                mine = [scan_members["index"].get(part) for part in parts]
                # Most splats have no object (-1). Another object's splats stay where they are.
                inside &= (labels == -1) | np.isin(labels, [i for i in mine if i is not None])
            left |= inside
        return left

    # Read the scene while nobody's waiting, so the first move or route after a move isn't slow.
    def warm_scene() -> None:
        try:
            splats_for_selection()
        except (HTTPException, OSError, ValueError) as error:
            print(f"Scene not read ahead: {error}")

    if grid is not None and os.getenv("SCENE_PLY"):
        threading.Thread(target=warm_scene, daemon=True).start()

    piece_files = Path(tempfile.mkdtemp(prefix="object-pieces-"))

    @app.get("/api/objects/{object_id}/home")
    def object_home(object_id: str) -> dict:
        """Say where an object's splats are in the scan, to hide them there when it's moved."""
        require(object_id)
        return {**store.home_box(object_id), "floor_margin": FLOOR_MARGIN}

    scan_members: dict[str, Any] = {}

    def members_of(asset: dict) -> np.ndarray | None:
        """Return where an object's own splats are in the scan, or None if that isn't known."""
        if not scan_members:
            folder = store.path.parent
            labels, final = folder / "splat_labels.npy", folder / "assets_final.json"
            scan_members["labels"] = np.load(labels) if labels.exists() else None
            names = json.loads(final.read_text())["assets"] if final.exists() else []
            scan_members["index"] = {a["object_id"]: i for i, a in enumerate(names)}
        ids = asset.get("combined_from") or [asset["object_id"]]
        indices = [scan_members["index"].get(object_id) for object_id in ids]
        labels = scan_members["labels"]
        positions = splats_for_selection().positions
        if labels is None or len(labels) != len(positions) or None in indices:
            return None
        return positions[np.isin(labels, indices)].astype(np.float64)

    @app.get("/api/objects/{object_id}/cover")
    def object_cover(object_id: str) -> dict:
        """Say what to hide in the scan to delete an object, without taking its neighbours."""
        # Not require: after a reload, the viewer asks about objects that are already deleted.
        asset = store.get(object_id)
        if asset is None:
            raise HTTPException(404, f"No object {object_id}")
        up = np.asarray(store.scene.get("up") or (0.0, -1.0, 0.0), dtype=np.float64)
        floor_height = store.scene.get("floor_y", 0.0) * float(up[int(np.argmax(np.abs(up)))])
        points = members_of(asset)
        home = store.home_box(object_id)
        if points is not None:
            points = points[points @ up > floor_height + FLOOR_MARGIN]
            limit = (np.asarray(home["bbox_min"]), np.asarray(home["bbox_max"]))
            boxes = cover_boxes(points, limit)
            if boxes:
                return {"boxes": boxes, "method": "the object's own splats"}
        low, high = (
            np.minimum(home["bbox_min"], home["bbox_max"]),
            np.maximum(home["bbox_min"], home["bbox_max"]),
        )
        axis = int(np.argmax(np.abs(up)))
        # Stop just above the floor, which stays.
        if up[axis] < 0:
            high[axis] = min(high[axis], store.scene.get("floor_y", 0.0) - FLOOR_MARGIN)
        else:
            low[axis] = max(low[axis], store.scene.get("floor_y", 0.0) + FLOOR_MARGIN)
        box = {"bbox_min": low.tolist(), "bbox_max": high.tolist()}
        return {"boxes": [box], "method": "the object's whole box"}

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
        clearance = clearance_with_footprints(floor_map(), footprints(store, ""), band)
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
    def plan_ifc(ids: str | None = None, room: bool | None = None) -> Response:
        """Return the BIM model for BIM tools, with objects as they stand now.

        ids, comma-separated, exports only those objects, such as the selected one or those a
        filter shows. The walls and floor come too when room is true, which is the default only
        for the whole model.
        """
        assets = store.visible()
        file_name = "model.ifc"
        if ids is not None:
            wanted = {object_id.strip() for object_id in ids.split(",") if object_id.strip()}
            if not wanted:
                raise HTTPException(400, "Choose at least one object to export")
            missing = wanted - {asset["object_id"] for asset in assets}
            if missing:
                raise HTTPException(404, f"Not in the room now: {', '.join(sorted(missing))}")
            assets = [asset for asset in assets if asset["object_id"] in wanted]
            file_name = ifc_file_name(assets[0]) if len(assets) == 1 else "selection.ifc"
        document = {**store.scene, "scene_id": store.scene_id, "assets": assets}
        model = build_model(
            document, shapes_where_they_stand(), plan_layout()["description"]["room"]
        )
        if not (ids is None if room is None else room):
            # Walls and the floor are the only elements without an object.
            model["elements"] = [e for e in model["elements"] if e["object_id"] is not None]
        headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
        text = ifc_text(model, file_name=file_name)
        return Response(text, media_type="application/x-step", headers=headers)

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
