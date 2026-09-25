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


def format_errors(response: dict, catalog_uris: set[str] | None = None) -> list[str]:
    """All A1/A2 rule violations for one ContextDeeplinkResponse."""
    errs = [f"schema: {e}" for e in schema_errors(response)]
    if errs:
        return errs
    contexts = response.get("contexts", [])
    if not contexts:
        errs.append("empty: no contexts")
    for gi, g in enumerate(contexts):
        where = f"contexts[{gi}]"
        if not GOAL_RE.match(g["goal"]):
            errs.append(f"{where}.goal format: {g['goal']!r}")
        if not 2 <= len(words(g["title"])) <= 3:
            errs.append(f"{where}.title must be 2–3 words: {g['title']!r}")
        if not 0.0 <= g["score"] <= 1.0:
            errs.append(f"{where}.score out of range: {g['score']}")
        if not g["actions"]:
            errs.append(f"{where}: no actions")
        for ai, a in enumerate(g["actions"]):
            aw = f"{where}.actions[{ai}]"
            d = a["description"]
            if not d.startswith("It will") or not 5 <= len(words(d)) <= 7:
                errs.append(f"{aw}.description must be 5–7 words starting 'It will': {d!r}")
            if not a["stepGroups"]:
                errs.append(f"{aw}: no stepGroups")
            for si, sg in enumerate(a["stepGroups"]):
                if not sg["steps"] or any(not s.strip() for s in sg["steps"]):
                    errs.append(f"{aw}.stepGroups[{si}]: empty steps")
                link = sg.get("actionableDeeplink")
                if a.get("category") == "auto" and not link:
                    errs.append(f"{aw}.stepGroups[{si}]: auto action without actionableDeeplink")
                for key in ("actionableDeeplink", "validationDeeplink"):
                    dl = sg.get(key)
                    if dl and catalog_uris is not None and dl["deeplink"] not in catalog_uris:
                        errs.append(f"{aw}.stepGroups[{si}].{key}: deeplink not in catalog: {dl['deeplink']}")
    errs += [f"url leak: {u}" for u in url_leaks(response)]
    return errs
