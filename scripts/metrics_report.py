"""Generate metrics.md in the Theme 2 guide's Appendix C template, from real runs.

    python scripts/metrics_report.py            # writes metrics.md

Every number below is measured by this script; nothing is typed in by hand.
"""
from __future__ import annotations

import json
import os
import platform
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sgte import llm  # noqa: E402
from sgte.cache import Cache  # noqa: E402
from sgte.catalog import get_catalog  # noqa: E402
from sgte.engine import split_interactions, troubleshoot  # noqa: E402
from sgte.grounding import grounding_rate  # noqa: E402
from sgte.parse import _sentences, clean_markup  # noqa: E402
from sgte.rules import format_errors, schema_errors, url_leaks  # noqa: E402
from sgte.text import cosine, embed, tokens  # noqa: E402
from sgte.variations import variations  # noqa: E402

DATA = ROOT / "data"
KIT = json.loads((DATA / "student_kit" / "siis_responses.json").read_text())["responses"]
UNSEEN = json.loads((DATA / "unseen_siis.json").read_text())["cases"]
PARA = json.loads((DATA / "paraphrases.json").read_text())["paraphrases"]
NO_VIABLE = {"What are Bixby Routines?"}
CAT = get_catalog()
UI_START = re.compile(r"^(?:\w+,\s+)?(tap|select|touch|press|open|swipe|navigate|go to|turn|drag|enter)\b", re.I)


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))] if xs else float("nan")


def timed(fn, *a):
    t = time.perf_counter()
    out = fn(*a)
    return out, (time.perf_counter() - t) * 1000


# ------------------------------------------------------------------ 1. compliance
def compliance():
    cases = [(r["original_query"], r["siis_response"]) for r in KIT] + \
            [(c["query"], c["siis_response"]) for c in UNSEEN if c["siis_response"]["title"] not in NO_VIABLE]
    outs = [troubleshoot(q, s) for q, s in cases]
    n = len(outs)
    schema_ok = sum(not schema_errors(o) for o in outs)
    rules_ok = sum(not format_errors(o) for o in outs)
    leaks = sum(len(url_leaks(o)) for o in outs)
    links = [sg[k] for o in outs for g in o["contexts"] for a in g["actions"] for sg in a["stepGroups"]
             for k in ("actionableDeeplink", "validationDeeplink") if sg.get(k)]
    valid = sum(l["deeplink"] in CAT.uris for l in links)
    autos = [a for o in outs for g in o["contexts"] for a in g["actions"] if a["category"] == "auto"]
    auto_ok = sum(all(sg["actionableDeeplink"] and sg["actionableDeeplink"]["deeplink"] in CAT.uris for sg in a["stepGroups"]) for a in autos)
    return {"n": n, "schema": schema_ok / n, "rules": rules_ok / n, "leaks": leaks,
            "catalog": valid / len(links) if links else 1.0, "n_links": len(links),
            "auto": auto_ok / len(autos) if autos else 1.0, "n_auto": len(autos), "outs": list(zip(cases, outs))}
