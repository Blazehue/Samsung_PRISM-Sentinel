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


def schema_errors(response: dict) -> list[str]:
    try:
        ContextDeeplinkResponse.model_validate(response)
        return []
    except ValidationError as e:
        return [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]


def url_leaks(obj) -> list[str]:
    blob = json.dumps(obj, ensure_ascii=False)
    # Deeplinks use the bixby:// scheme — allowed; anything web-like is a leak.
    return [m.group(0) for m in URL_PATTERN.finditer(blob) if not m.group(0).startswith("bixby://")]
