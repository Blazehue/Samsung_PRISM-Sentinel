"""Output format rules from the Theme 2 FAQ (block A1 + gates G4/G5), in one
place so the engine, tests and the local scorer agree."""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from .kit_schema import ContextDeeplinkResponse
from .text import URL_PATTERN

GOAL_RE = re.compile(r"^Follow these steps to perform this .+ (Troubleshooting|Configuration)\.?$")


def words(s: str) -> list[str]:
    return [w for w in re.split(r"\s+", (s or "").strip()) if w]
