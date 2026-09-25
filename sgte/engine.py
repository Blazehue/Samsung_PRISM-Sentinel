"""SIIS response + user query → ContextDeeplinkResponse.

Stage 1 (understand): enrich the query and parse the SIIS text into sections
and verbatim step groups.
Stage 2 (compose): one Action per screen/feature (a section, or each labelled
group inside it), one physical interaction per step, deeplinks resolved per
step group, actions ordered least-disruptive first and critical last, then
every field is shaped to the format rules and schema-validated.
"""
from __future__ import annotations

import contextvars
import re
import time
from concurrent.futures import ThreadPoolExecutor

from . import llm
from .catalog import DUMMY, get_catalog
from .enrich import HOW_TO, ISSUE_WORDS, enrich, symptoms_of
from .kit_schema import ContextDeeplinkResponse
from .parse import VERBS, Group, Section, _sentences, _tidy, clean_markup, parse_siis
from .parse import HEADER as MD_HEADER
from .text import STOP, URL_PATTERN, strip_urls, tokens

MAX_ACTIONS = 10

# Guide §4.1 — critical: disruptive or irreversible operations (factory reset,
# restart, firmware update, safe mode…); FAQ — also safety-related. Must be last.
CRITICAL = re.compile(
    r"\b(factory (data )?reset|reset (all|network) settings|erase|wipe|delete all|clear (the )?(app'?s )?data|"
    r"(force |soft )?restart\w*|reboot\w*|safe mode|(software|firmware|system) update\w*|update the software|"
    r"swell\w*|swollen|overheat\w*|smoke|burn\w*|liquid damage|water damage|got wet)\b", re.I)
# Manual escalations (service centre, support, provider) come after self-service manual steps.
ESCALATION = re.compile(r"\b(contact|service cent(er|re)|repair|support|provider|visit)\b", re.I)
RANK = {"auto": 0, "manual": 1, "critical": 3}

SMALL = {"a", "an", "the", "your", "my", "of", "on", "in", "to", "for", "and", "or", "with", "from", "at", "by"}
TRAILING_BAD = SMALL | {"if", "when", "is", "are", "does", "not", "but", "so", "while"}

# First word of a section title → how the description starts ("It will …").
VERB_PHRASE = {
    "check": "check", "verify": "verify", "review": "review", "clear": "clear", "restart": "restart",
    "restarting": "restart", "reboot": "restart", "force": "force", "charge": "charge", "attempt": "attempt to",
    "contact": "help you contact", "use": "help you use", "using": "help you use", "customize": "customize",
    "customise": "customize", "create": "create", "remove": "remove", "exit": "exit", "open": "open",
    "select": "select", "mirror": "mirror", "disconnect": "disconnect", "access": "help you access",
    "adjust": "adjust", "test": "test", "perform": "perform", "update": "update", "transfer": "transfer",
    "enable": "enable", "disable": "disable", "turn": "turn", "reset": "reset", "back": "back up",
    "troubleshooting": "troubleshoot", "fix": "fix", "connect": "connect", "swipe": "use swipe",
    "configure": "configure", "manage": "manage", "set": "set up", "choose": "choose", "change": "change",
}
