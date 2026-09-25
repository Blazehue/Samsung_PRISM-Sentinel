"""Local mirror of the Theme 2 gates (G2–G5) and automated blocks (A1–A5).

    python scripts/local_score.py                 # in-process (FastAPI TestClient)
    python scripts/local_score.py --url http://host:8000   # against a live deployment
    python scripts/local_score.py --json out.json # also write the numbers

Thresholds are the FAQ's; the point totals are our own estimate of how the
official scorer weights each block, for tracking regressions.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sgte.catalog import get_catalog  # noqa: E402
from sgte.grounding import grounding_rate  # noqa: E402
from sgte.rules import format_errors, schema_errors, url_leaks  # noqa: E402
from sgte.text import jaccard, tokens  # noqa: E402

KIT = ROOT / "data" / "student_kit" / "siis_responses.json"
UNSEEN = ROOT / "data" / "unseen_siis.json"
PARA = ROOT / "data" / "paraphrases.json"
NO_VIABLE = {"What are Bixby Routines?"}        # unseen article with no instructions at all


def p95(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(0.95 * len(xs)))] if xs else None
