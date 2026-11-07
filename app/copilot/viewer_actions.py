"""Turn what someone says to Val into a viewer action, the same ones as the buttons.

Each action has keywords, so the wording can vary: "hide the frames" and "turn the boxes off" are
the same action. Val only changes the 3D view this way, never plant equipment. check_safety runs
first.
The actions themselves are listed in app/api/commands.py.
"""

import re
from dataclasses import dataclass, field
from typing import Any

LEAD = re.compile(
    r"^(?:(?:please|val|hey|ok|okay|now|just|can you|could you|would you|will you|i want to|"
    r"i'd like to|let's|lets|go ahead and)[\s,]+)+"
)
QUESTION = re.compile(r"^(?:what|what's|why|when|how|is|are|does|did|who|which|where|where's)\b")
FRAMES = r"\b(?:frames?|box(?:es)?|outlines?)\b"
SHOW = r"\b(?:show|turn on|turn|switch on|enable|display|open|enter|start)\b"
HIDE = r"\b(?:hide|turn off|switch off|disable|remove|leave|exit|close|stop)\b"
THING = r"(?:it|this|that|the\s+\S+(?:\s+\S+)?|\S+-\d+)"


@dataclass
class Match:
    """An action to run. `needs_object` means it acts on a device or object."""

    action: str
    say: str
    args: dict[str, Any] = field(default_factory=dict)
    needs_object: bool = False


def _simple(question: str) -> Match | None:
    """Actions that take no object."""
    if re.search(r"\bstop\s+(?:walking|following|the walk)\b", question):
        return Match("stop_walking", "Stopped walking.")
    if re.search(r"\b(?:walk|follow)\b.*\b(?:route|path)\b|^start walking\b", question):
        return Match("walk_route", "Walking along the route.")
    if re.search(r"\b(?:clear|remove|delete|hide|cancel)\b.*\b(?:route|path)\b", question):
        return Match("clear_route", "Route removed.")
    profile = re.search(
        r"\b(robot|person)\s+(?:route|path|profile|mode)\b|"
        r"\b(?:route|profile)\s+for\s+(?:a\s+)?(robot|person)\b|\buse\s+(?:the\s+)?(robot|person)\b",
        question,
    )
    if profile:
        chosen = next(group for group in profile.groups() if group)
        return Match("set_profile", f"Routes are now for a {chosen}.", {"profile": chosen})
    mode = re.search(
        r"\b(walk|fly)\s+mode\b|\b(?:switch|change|go)\s+to\s+(walk|fly)(?:ing)?\b|^(walk|fly)$",
        question,
    )
    if mode:
        chosen = next(group for group in mode.groups() if group)
        return Match("set_mode", f"Now in {chosen} mode.", {"mode": chosen})
    if re.search(FRAMES, question):
        if re.search(HIDE, question) or re.search(r"\bturn\b.*\boff\b", question):
            return Match("set_boxes", "Object frames are hidden.", {"on": False})
        if re.search(SHOW, question):
            return Match("set_boxes", "Object frames are showing.", {"on": True})
    near = re.search(r"\b(?:range|within|radius|distance)\b.*?(\d+)", question)
    if near:
        metres = int(near.group(1))
        return Match("set_range", f"Showing objects within {metres} m.", {"metres": metres})
    view = re.search(
        r"\b(scan|objects?|both)\s+(?:view|only)\b|\b(?:only|just)\s+(?:the\s+)?(scan|objects?)\b|"
        r"\bshow\s+(?:me\s+)?(?:the\s+)?(scan|objects?|both)\b",
        question,
    )
    if view:
        chosen = next(group for group in view.groups() if group)
        chosen = "objects" if chosen.startswith("object") else chosen
        return Match("set_view", f"Showing {chosen}.", {"view": chosen})
    if re.search(r"\b(?:pull|move|spread|take)\b.*\bapart\b", question):
        return Match("set_apart", "Objects are pulled apart.", {"on": True})
    if re.search(r"\b(?:bring|put|move)\b.*\btogether\b", question):
        return Match("set_apart", "Objects are back together.", {"on": False})
    if re.search(r"\bbim\b", question):
        if re.search(HIDE, question):
            return Match("set_bim", "Left the BIM model.", {"on": False})
        return Match("set_bim", "Showing the BIM model.", {"on": True})
    if re.search(r"\breset\b.*\bview\b|\bback to (?:the )?start|\bstarting position\b", question):
        return Match("reset_view", "Back at the starting position.")
    if re.search(r"\bundo\b.*\b(?:changes?|all|everything|moves?)\b", question):
        return Match("undo_changes", "All changes are undone.")
    if re.search(r"\bclose\b.*\b(?:panels?|windows?|details|val|chat)\b", question):
        return Match("close_panels", "Closed.")
    if re.search(r"\badd\b.*\b(?:object|box|item|thing)\b", question):
        return Match("start_add", "Draw around the new object.")
    if re.fullmatch(r"done|finish(?:ed)?|finish (?:moving|turning|rotating)|stop moving", question):
        return Match("finish_moving", "Finished.")
    return None


def _on_object(question: str) -> Match | None:
    """Actions on one device or object. The caller finds which, and never guesses."""
    if re.match(r"(?:select|pick|highlight|focus on)\b", question):
        return Match("select", "Selected {name}.", needs_object=True)
    if re.match(r"(?:duplicate|copy|clone)\b", question):
        return Match("duplicate_object", "Copied {name} in the viewer.", needs_object=True)
    if re.match(r"(?:delete|remove)\b", question):
        return Match(
            "delete_object",
            "Deleted {name} from the viewer. Undo brings it back.",
            needs_object=True,
        )
    named = re.match(rf"(?:rename|name|call)\s+{THING}\s+(?:to\s+|as\s+)?(.+)$", question)
    if named:
        text = named.group(1).strip(" '\"")
        return Match("rename_object", f"Named it {text}.", {"name": text}, needs_object=True)
    if re.match(r"(?:rename|name|call)\b", question):
        return Match("rename_object", "What should I call it?", needs_object=False)
    position = re.match(
        r"(?:move|drag)\b.*?\bto\s+(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)$",
        question,
    )
    if position:
        where = [float(value) for value in position.groups()]
        return Match(
            "move_object", "Moved {name} in the viewer.", {"position": where}, needs_object=True
        )
    if re.match(r"(?:move|drag)\b", question):
        return Match(
            "start_move", "Drag {name} to its new spot, then press Done.", needs_object=True
        )
    turned = re.match(r"(?:rotate|turn)\b.*?\b(to|by)?\s*(-?\d+)\s*(?:deg\w*|°)?$", question)
    if turned:
        action = "rotate_object" if turned.group(1) == "to" else "turn_object"
        degrees = float(turned.group(2))
        return Match(
            action,
            f"Turned {{name}} in the viewer, {degrees:.0f} degrees.",
            {"degrees": degrees},
            needs_object=True,
        )
    if re.match(rf"(?:rotate|turn)\s+{THING}$", question):
        return Match("start_rotate", "Turn {name}, then press Done.", needs_object=True)
    if re.match(r"split\b", question):
        return Match("start_split", "Draw around one part of {name}.", needs_object=True)
    if re.match(r"(?:combine|merge|join)\b", question):
        return Match("start_combine", "Tap the object to combine with {name}.", needs_object=True)
    return None


def match_action(question: str) -> Match | None:
    """Return the viewer action this sentence asks for, or None if it isn't one."""
    clean = re.sub(r"[.!?,]+$", "", question.strip().lower())
    clean = LEAD.sub("", clean)
    clean = re.sub(r"\s+(?:please|for me|now)$", "", clean)
    if QUESTION.match(clean):
        return None
    found = _simple(clean) or _on_object(clean)
    if found and found.action == "rename_object" and found.args:
        # Everything above reads lower case, but a name keeps the capitals it was given.
        at = question.lower().rfind(found.args["name"])
        found.args["name"] = question[at : at + len(found.args["name"])]
        found.say = f"Named it {found.args['name']}."
    return found
