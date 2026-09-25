"""Step grounding: is every output step present in the SIIS text?"""
from __future__ import annotations

import re


def _canon(s: str) -> str:
    s = s.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def grounded(step: str, content: str) -> bool:
    return _canon(step) in _canon(content)


def grounding_rate(response: dict, siis: dict) -> tuple[int, int]:
    """(grounded steps, total steps) for one response."""
    # Compare against the article's text, not its markup: "<li>Open <b>Settings</b></li>" grounds "Open Settings."
    content = re.sub(r"<[^>]+>", " ", f"{siis.get('title', '')}\n{siis.get('content', '')}")
    steps = [s for g in response.get("contexts", []) for a in g["actions"] for sg in a["stepGroups"] for s in sg["steps"]]
    return sum(grounded(s, content) for s in steps), len(steps)
