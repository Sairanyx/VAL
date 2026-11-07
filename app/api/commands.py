"""Commands for the viewer: every action on the tablet, so the voice copilot can do them too.

A copilot or script posts a command, the open viewer picks it up by polling, runs it through the
same code as its buttons, and reports the result. Some actions need a finger, such as drawing a box
around an object, so those only start the action here.
"""

from collections import deque
from typing import Any

MAX_KEPT = 200
OBJECT = {"object_id": "str"}

ACTIONS: dict[str, dict[str, Any]] = {
    "select": {"args": OBJECT, "does": "Select an object and open its details"},
    "close_panels": {"args": {}, "does": "Close the details and Val windows"},
    "duplicate_object": {"args": OBJECT, "does": "Copy an object to a free spot beside it"},
    "delete_object": {"args": OBJECT, "does": "Delete an object. Undo changes brings it back"},
    "route_to": {"args": OBJECT, "does": "Show a route to an object"},
    "go_to_fault": {"args": {}, "does": "Show a route to the faulty device"},
    "clear_route": {"args": {}, "does": "Remove the route"},
    "walk_route": {"args": {}, "does": "Walk along the route"},
    "stop_walking": {"args": {}, "does": "Stop walking"},
    "set_profile": {"args": {"profile": "str"}, "does": "Route for a person or robot"},
    "set_mode": {"args": {"mode": "str"}, "does": "Move as walk or fly"},
    "set_boxes": {"args": {"on": "bool"}, "does": "Show or hide object frames"},
    "set_range": {"args": {"metres": "number"}, "does": "How far away objects are shown"},
    "set_view": {"args": {"view": "str"}, "does": "Show scan, both, or objects"},
    "set_apart": {"args": {"on": "bool"}, "does": "Pull objects apart, or bring them together"},
    "set_bim": {"args": {"on": "bool"}, "does": "Show or leave the BIM model"},
    "reset_view": {"args": {}, "does": "Go back to the starting position"},
    "open_copilot": {"args": {}, "does": "Open Val"},
    "ask_copilot": {"args": {"question": "str"}, "does": "Ask Val and show the answer"},
    "move_object": {
        "args": {"object_id": "str", "position": "list"},
        "does": "Move an object, if the spot is free",
    },
    "rotate_object": {
        "args": {"object_id": "str", "degrees": "number"},
        "does": "Turn an object to this angle, if it fits",
    },
    "turn_object": {
        "args": {"object_id": "str", "degrees": "number"},
        "does": "Turn an object by this much, if it fits",
    },
    "start_move": {"args": OBJECT, "does": "Let the user drag an object"},
    "start_rotate": {"args": OBJECT, "does": "Let the user turn an object"},
    "finish_moving": {"args": {}, "does": "Finish moving or turning"},
    "undo_changes": {"args": {}, "does": "Undo all changes to the scene"},
    "start_add": {"args": {}, "does": "Start adding an object: the user draws around it"},
    "start_split": {"args": OBJECT, "does": "Start splitting an object: the user draws one part"},
    "start_combine": {"args": OBJECT, "does": "Start combining: the user taps the other object"},
}
TYPES = {"str": str, "bool": bool, "number": (int, float), "list": list}


def problem_with(action: str, args: dict[str, Any]) -> str | None:
    """Return why a command isn't valid, or None if it is."""
    spec = ACTIONS.get(action)
    if spec is None:
        return f"Unknown action {action!r}. See GET /api/viewer/actions."
    for name, kind in spec["args"].items():
        if name not in args:
            return f"{action} needs {name}."
        wrong_bool = kind == "number" and isinstance(args[name], bool)
        if wrong_bool or not isinstance(args[name], TYPES[kind]):
            return f"{name} must be a {kind}."
    position = args.get("position")
    if position is not None and len(position) != 3:
        return "position must have 3 numbers."
    return None


class CommandQueue:
    """Recent commands in order. Old ones drop off, as they only matter while a viewer is open."""

    def __init__(self) -> None:
        self.commands: deque[dict[str, Any]] = deque(maxlen=MAX_KEPT)
        self.last_id = 0

    def add(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        self.last_id += 1
        command = {"id": self.last_id, "action": action, "args": args, "result": None}
        self.commands.append(command)
        return command

    def after(self, command_id: int) -> list[dict[str, Any]]:
        return [command for command in self.commands if command["id"] > command_id]

    def get(self, command_id: int) -> dict[str, Any] | None:
        return next((c for c in self.commands if c["id"] == command_id), None)
