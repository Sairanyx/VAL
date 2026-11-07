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


# What people call each filter. The keys are the ones in web/colors.js.
TYPE_WORDS = {
    "pump": "pump",
    "motor": "motor",
    "valve": "valve",
    "tank": "tank",
    "pipe": "pipe",
    "hose": "pipe",
    "fitting": "pipe",
    "cable": "cable",
    "cabinet": "cabinet",
    "panel": "cabinet",
    "light": "light",
    "lamp": "light",
    "sensor": "sensor",
    "transmitter": "sensor",
    "gauge": "sensor",
    "chair": "furniture",
    "shelf": "furniture",
    "shelve": "furniture",
    "furniture": "furniture",
    "cart": "portable",
    "tool": "portable",
    "ladder": "portable",
    "bucket": "portable",
    "bag": "portable",
}
CONDITION_WORDS = {
    r"attention(?: required)?|urgent|critical|faulty|faults?|broken|red": "attention_required",
    r"degraded|yellow": "degraded",
    r"watch(?:ed|list)?": "watch",
    r"healthy|fine|ok|okay|green": "healthy",
    r"no records?|unlinked|without (?:a )?records?|unmapped": "none",
}
STAGE_WORDS = {
    r"go dark|darkness|dark view": ("dark", "Darkness."),
    r"simple bim|box bim": ("box", "Simple BIM."),
    r"blob bim|mesh bim|blobs": ("mesh", "Blob BIM."),
    r"point cloud|points view": ("points", "The point cloud."),
    r"real view|real room": ("real", "The real view."),
}
FILTER_VERB = r"\b(?:only|just|filter|show|display|highlight|see|list)\b"
GENERIC_THINGS = r"(?:equipment|devices?|objects?|things?|items?|assets?)"


# Measured moves. Distances are in the scan's units, which look close to metres but aren't checked.
NUMBER_WORDS = {
    "half a": 0.5,
    "a half": 0.5,
    "one": 1,
    "a": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
UNITS = {"m": 1.0, "metre": 1.0, "meter": 1.0, "cm": 0.01, "centimetre": 0.01, "centimeter": 0.01}
DIRECTIONS = {
    "left": "left",
    "right": "right",
    "forward": "forward",
    "forwards": "forward",
    "ahead": "forward",
    "away": "forward",
    "back": "back",
    "backward": "back",
    "backwards": "back",
    "closer": "back",
    "towards me": "back",
    "toward me": "back",
    "up": "up",
    "higher": "up",
    "down": "down",
    "lower": "down",
}
_NUMBERS = "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))
_UNIT_WORDS = r"m|metres?|meters?|cm|centimetres?|centimeters?"
AMOUNT = rf"(\d+(?:\.\d+)?|{_NUMBERS})\s*({_UNIT_WORDS})\b"
NEAR = (
    r"(?:as close as (?:possible|you can|it can go) to|next to|close to|closer to|beside|near"
    r"|up against|by)"
)


def _distance(amount: str, unit: str) -> float:
    value = float(NUMBER_WORDS[amount]) if amount in NUMBER_WORDS else float(amount)
    return value * UNITS[unit.rstrip("s")]


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


def _words_in(question: str) -> tuple[list[str], list[str]]:
    """Return the types and conditions a sentence names."""
    types = sorted(
        {key for word, key in TYPE_WORDS.items() if re.search(rf"\b{word}(?:s|es)?\b", question)}
    )
    conditions = sorted(
        {key for words, key in CONDITION_WORDS.items() if re.search(rf"\b(?:{words})\b", question)}
    )
    return types, conditions


def _filters(question: str, asked: str) -> Match | None:
    """The demo, filters, alerts, and the Map and Objects panels.

    `asked` is the whole sentence, because "just" and "only" can be cleaned off the start.
    """
    for words, (stage, say) in STAGE_WORDS.items():
        if re.search(rf"\b(?:{words})\b", question):
            return Match("set_stage", say, {"stage": stage})
    if re.search(r"\b(?:next|change|switch)(?: the)? view\b", question):
        return Match("next_stage", "Next view.")
    if re.search(r"\b(?:demo|tour|tutorial)\b", question):
        if re.search(r"\b(?:stop|end|cancel|exit|leave|finish)\b", question):
            return Match("stop_demo", "Tutorial stopped.")
        if re.search(r"\b(?:start|run|play|begin|show|give|do|take)\b", question):
            return Match("start_demo", "Starting the tutorial.")
    everything = (
        rf"^(?:show|display)\s+(?:me\s+)?(?:all|everything|all (?:the\s+)?{GENERIC_THINGS})$"
    )
    cleared = r"\b(?:clear|reset|remove)\b.*\bfilters?\b|\bno filters?\b"
    if re.search(cleared, question) or re.search(everything, question):
        return Match("clear_filters", "Showing everything.")
    if re.search(r"\balerts?\b|\bwarnings?\b", question):
        if re.search(r"\b(?:off|hide|stop|disable|no)\b", question):
            return Match("set_alerts", "Alerts are off.", {"level": "off"})
        if re.search(r"\b(?:all|every|everything|on)\b", question):
            return Match("set_alerts", "Showing all alerts.", {"level": "all"})
        if "degraded" in question:
            return Match("set_alerts", "Alerts for attention and degraded.", {"level": "degraded"})
        return Match("set_alerts", "Alerts only for attention required.", {"level": "attention"})
    if re.search(r"\bfilters?\b", question) and re.search(r"\b(?:open|show)\b", question):
        return Match("open_filters", "Here are the filters.")
    if re.search(r"\b(?:map|minimap|plan)\b", question):
        found = re.search(r"\bfind\s+(.+?)\s+on\s+the\s+(?:map|plan)$", question)
        if found:
            text = found.group(1).upper() if "-" in found.group(1) else found.group(1)
            return Match("find_on_map", f"Looking for {text} on the map.", {"text": text})
        if re.search(HIDE, question):
            return Match("close_map", "Map hidden.")
        if re.search(r"\b(?:full|big|bigger|expand|enlarge|large)\b", question):
            return Match("expand_map", "Here's the full map.")
        if re.search(r"\b(?:open|show|see|go to|display)\b", question):
            return Match("open_map", "Here's the map.")
    if re.search(r"\b(?:objects?|equipment)\s+(?:list|panel)\b|\blist of\b", question):
        if re.search(HIDE, question):
            return Match("close_list", "Closed the list.")
        return Match("open_list", "Here's the list.")
    if re.search(r"\b[a-z]{1,3}-\d+\b", question):
        return None  # A named device isn't a filter.
    if re.match(r"(?:hide|remove)\b", question):
        types, _ = _words_in(question)
        if types:
            return Match("hide_types", f"Hiding {', '.join(types)}.", {"types": types})
    if re.search(FILTER_VERB, asked):
        types, conditions = _words_in(question)
        mobility = "any"
        if re.search(r"\bmovable\b|\bcan move\b", question):
            mobility = "movable"
        elif re.search(r"\bfixed\b|\bcan't move\b", question):
            mobility = "fixed"
        if types or conditions or mobility != "any":
            parts = [*types, *(c.replace("_", " ") for c in conditions)]
            if mobility != "any":
                parts.append(mobility)
            return Match(
                "set_filter",
                f"Showing only: {', '.join(parts)}.",
                {"types": types, "conditions": conditions, "mobility": mobility},
            )
    return None


def _on_object(question: str) -> Match | None:
    """Actions on one device or object. The caller finds which, and never guesses."""
    if re.match(r"focus(?: on)?\b", question):
        return Match("focus_object", "Here's {name}.", needs_object=True)
    if re.match(r"(?:select|pick|highlight)\b", question):
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
    measured = re.match(
        rf"(?:move|drag|push|shift|slide)\b.*?\b{AMOUNT}(?:\s+to\s+the)?\s+(.+)$", question
    )
    if measured:
        amount, unit, rest = measured.groups()
        direction = next(
            (key for word, key in DIRECTIONS.items() if re.match(rf"{word}\b", rest.strip())), None
        )
        if direction:
            metres = round(_distance(amount, unit), 3)
            return Match(
                "move_by",
                f"Moving {{name}} {metres:g} m {direction}.",
                {"metres": metres, "direction": direction},
                needs_object=True,
            )
    near = re.match(rf"(?:move|drag|put|push|place|bring)\b.*?\b{NEAR}\s+(.+)$", question)
    if near:
        other = near.group(1).strip(" '\"")
        return Match(
            "move_near",
            f"Moving {{name}} next to {other}.",
            {"near": other},
            needs_object=True,
        )
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
    found = _filters(clean, question.lower()) or _simple(clean) or _on_object(clean)
    if found and found.action == "rename_object" and found.args:
        # Everything above reads lower case, but a name keeps the capitals it was given.
        at = question.lower().rfind(found.args["name"])
        found.args["name"] = question[at : at + len(found.args["name"])]
        found.say = f"Named it {found.args['name']}."
    return found
