"""What counts as a request to operate plant equipment. Used by check_safety in guardrails.py.

Spoken and typed requests are short and often have no object ("Shut down", "Isolate"), so a verb
that only means operating equipment is refused at the start of a sentence. Words with everyday
uses, such as "open", "close" or "stop", need equipment after them, so "Stop walking" and "Close
Val" still work.
"""

TAG = r"[a-z]{1,3}-\d+"
EQUIPMENT = r"pump|motor|valve|damper|breaker|equipment|machine|compressor|fan|tank|boiler"
# Words a person may say before the request itself.
LEAD = (
    r"^(?:(?:please|val|hey|ok|okay|now|just|immediately|go ahead and|can you|could you|would you|"
    r"will you|can i|could i|may i|should i|shall i|how do i|how can i|how to|let's|lets|let me|"
    r"i want to|i want you to|i need to|i need you to|i'd like to|we need to|you should|you must|"
    r"help me)[\s,]+)*"
)
NOT_OBJECT = r"(?!\s+(?:procedure|sequence|history|log|status|date|time)\b)"
# Viewer settings that can be turned on and off without touching the plant.
VIEWER_THING = r"(?:the\s+)?(?:frames?|box(?:es)?|outlines?|bim|labels?)\b"

AUTONOMOUS_CONTROL_PATTERNS = [
    LEAD + r"(?:shut\s*down|power\s+(?:down|off)|isolate|actuate|de-?pressuri[sz]e|pressuri[sz]e|"
    r"restart|reboot|lock\s*out)\b" + NOT_OBJECT,
    LEAD + r"(?:drain|flush)\b(?!\s+(?:valve|line|point|pipe|port|plug)\b)" + NOT_OBJECT,
    LEAD + r"(?:start|stop|restart|open|close)\s+(?:it|this|that)(?:\s+(?:one|now|please|down))*$",
    rf"\b(?:isolate|actuate|de-?pressuri[sz]e|pressuri[sz]e)\s+"
    rf"(?:it\b|this\b|that\b|the\s|{TAG}|{EQUIPMENT})",
    rf"\b(?:drain|flush)\s+(?:it\b|this\b|that\b|the\s|{TAG})",
    rf"\b(?:turn|switch)\s+(?:on|off)\b(?!\s+{VIEWER_THING})",
    rf"\b(?:shut|power|turn|switch)\s+(?!{VIEWER_THING})"
    rf"(?:it|this|that|the\s+(?:[a-z0-9\-]+\s+)?[a-z0-9\-]+|{TAG})\s+(?:down|off|on)\b",
    rf"\b(?:start|stop|restart|shutdown|shut\s+down)(?:ing|s|ped)?\s+(?:the\s+)?"
    rf"(?:[a-z0-9_\-]+\s+)?(?:{EQUIPMENT})\b",
    rf"\b(?:start|stop|restart|shutdown|shut\s+down)(?:ing|s|ped)?\s+(?:the\s+)?{TAG}\b",
    r"\b(?:open|close)\s+(?:the\s+)?(?:[a-z0-9_\-]+\s+)?(?:valve|damper|breaker)\b",
    rf"\b(?:open|close)\s+(?:the\s+)?{TAG}\b",
    r"\b(?:turn|rotate)\s+(?:the\s+)?(?:[a-z0-9_\-]+\s+)?valve\b",
    r"\b(?:increase|decrease|change|set)\s+(?:the\s+)?(?:[a-z0-9_\-]+\s+)?"
    r"(?:pressure|speed|flow|setpoint|power|rpm)\b",
    r"\b(?:overrid(?:e|es|ing)|bypass(?:es|ing|ed)?|disabl(?:e|es|ing)|clear(?:s|ing)?|"
    r"acknowledg(?:e|es|ing)|reset(?:s|ting)?)\s+(?:the\s+|an?\s+)?(?:[a-z0-9_\-]+\s+)?"
    r"(?:alarm|interlock|safety|trip)s?\b",
    r"\b(?:silence|mute)\s+(?:the\s+|this\s+|that\s+)?(?:[a-z0-9_\-]+\s+)?(?:alarm|trip)s?\b",
    r"\bexecute\s+(?:remote\s+)?control\b",
]

# Asking what a word means is not asking anyone to do it.
DEFINITION = (
    r"^(?:what\s+(?:does|do)\s+.+\s+mean|what\s+is\s+meant\s+by\s+.+|"
    r"(?:what\s+is\s+)?the\s+meaning\s+of\s+.+|meaning\s+of\s+.+|define\s+.+)$"
)
SENTENCE_END = r"[.!?;]+(?:\s+|$)|\n"
