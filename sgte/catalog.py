"""Deeplink catalogue: semantic matching of step groups to masked deeplinks.

URIs are masked, so matching uses description + message + qna_description.
A match is accepted only when a *specific* on-screen label named in the steps
(e.g. "Clear cache", "Screen timeout") also appears in the catalogue entry —
BM25 alone happily returns plausible-but-wrong links.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .text import BM25, tokens

DATA = Path(__file__).resolve().parent.parent / "data" / "student_kit" / "deeplinks.json"
DUMMY = "bixby://dummy_positive"

# Words that name *where* you are, not *what* you change — never enough to justify a link.
GENERIC = set(tokens(
    "settings setting quick panel menu screen icon button option options app apps page home tap select "
    "open navigate go device more feature features general advanced top bottom right left side switch toggle "
    "view power button enable disable turn on off show use issue issues problem problems step steps check "
    "mode add adjust now access set change remove new start done ok yes allow confirm restart try"
))

TARGET = re.compile(
    r"\b(?i:tap|touch|select|choose|open|enable|disable|turn on|turn off|toggle|go to|navigate to|find|search for)\s+"
    r"(?:on\s+)?(?:the\s+)?([A-Z0-9][\w\-'/&+ ]{1,60}?)(?=\s*(?:[,.;:(]|\band\b|\bthen\b|\bto\b|\bwhen\b|\bif\b|\bnext\b|$))"
)
SETTINGS_PATH = re.compile(r"Settings\s*>\s*([^.,;]+)")
# "tap the switch next to Touch sensitivity", "the Auto rotate toggle"
SWITCH_NEXT = re.compile(r"(?i:switch(?:es)?|toggle|slider)\s+(?i:next to|beside|for)\s+([A-Z][\w\-' ]{1,45}?)(?=\s*(?:[,.;:(]|\band\b|\bor\b|\bto\b|$))")
# "turn off", "turn it off", "switch the Wi-Fi off", "disable it" … — whichever is mentioned last wins.
_OBJ = r"(?:\s+(?:it|this|that|them|this feature|the [\w-]+(?: [\w-]+)?))?"
OFF = re.compile(r"\b(?:turn|switch|toggle)" + _OBJ + r"\s+off\b|\bdisable\b|\bdeactivate\b", re.I)
ON = re.compile(r"\b(?:turn|switch|toggle)" + _OBJ + r"\s+on\b|\benable\b|\bactivate\b|\btap the switch(?:es)?\b", re.I)
# "Drag the slider…", "choose a longer time", "set it to 30 seconds": the step sets a value.
ADJUST = re.compile(r"\b(?:drag|slide|move) the slider|\badjust the (?:level|size|value|brightness|volume)\b|"
                    r"\bchoose a (?:longer|shorter|higher|lower|different)\b|\bset (?:it|the [\w ]{1,20}) to\b", re.I)
VERB_PREFIX = re.compile(r"^(?:View|Enable|Disable|Adjust|Check|Open|Set|Switch|Increase|Diagnose|Optimize)\s+", re.I)
DESC_LABEL = [re.compile(p) for p in (r"^Opens the (.+?) settings? (?:page )?in ", r"^Opens the (.+?) (?:page|screen|settings) ",
                                         r"^(?:Enables|Disables) (.+?) via ", r"^Opens (?:the )?(.+?) (?:in|via) ")]

# Words that name UI furniture, not a setting — never enough on their own.
CHROME = set(tokens("more options option menu settings setting button buttons icon home back page tab ok done next "
                    "cancel apply save all general advanced other show view"))

# Confirmation buttons are where a flow *ends*, not the screen it is about.
BUTTONS = {"delete all", "delete", "reset", "ok", "restart", "confirm", "done", "allow", "start", "start now",
           "yes", "no", "cancel", "apply", "save", "disconnect", "remove", "erase", "next", "continue",
           "turn off", "power off", "reset settings", "remove device", "add device", "unpair", "pair", "forget",
           "install", "download and install", "update", "unrestricted", "uninstall", "force stop"}


@dataclass
class Entry:
    id: str
    deeplink: str
    description: str
    message: str
    original_type: str | None
    qna: str
    validation: dict | None
    toks: set


@dataclass
class Match:
    entry: Entry
    score: float
    matched_terms: list[str]


class Catalog:
    def __init__(self, path: Path = DATA):
        raw = json.loads(Path(path).read_text())["deeplinks"]
        self.entries: list[Entry] = []
        docs = []
        for e in raw:
            if e["deeplink"] == DUMMY:
                continue
            text = f"{e.get('message','')} {e.get('message','')} {e.get('description','')} {e.get('qna_description','')}"
            toks = tokens(text)
            self.entries.append(Entry(
                id=e["id"], deeplink=e["deeplink"], description=e.get("description") or "",
                message=e.get("message") or "", original_type=e.get("originalType"),
                qna=e.get("qna_description") or "", validation=e.get("validation"), toks=set(toks),
            ))
            docs.append(toks)
        self.bm25 = BM25(docs)
        # Exact on-screen label → entries. "View Bluetooth" and the description's
        # "Opens the Bluetooth settings page…" both give the label "bluetooth".
        self.by_label: dict[str, list[int]] = {}
        for i, e in enumerate(self.entries):
            for lab in self.labels_of(e):
                self.by_label.setdefault(lab, []).append(i)
        self.uris = ({e.deeplink for e in self.entries} | {DUMMY}
                     | {e.validation["deeplink"] for e in self.entries if e.validation})
