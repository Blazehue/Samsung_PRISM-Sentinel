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
