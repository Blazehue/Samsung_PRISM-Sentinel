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
