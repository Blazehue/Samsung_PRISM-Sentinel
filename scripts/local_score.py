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


class Client:
    def __init__(self, url: str | None):
        if url:
            import httpx
            self.c, self.base = httpx.Client(timeout=30), url.rstrip("/")
        else:
            from fastapi.testclient import TestClient
            import app as app_module
            self.c, self.base = TestClient(app_module.app).__enter__(), ""

    def get(self, path):
        return self.c.get(self.base + path)

    def post(self, path, body):
        t = time.perf_counter()
        r = self.c.post(self.base + path, json=body)
        return r, (time.perf_counter() - t) * 1000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--json")
    args = ap.parse_args()
    cli = Client(args.url)
    uris = get_catalog().uris
    rows = json.loads(KIT.read_text())["responses"]
    unseen = json.loads(UNSEEN.read_text())["cases"]
    out: dict = {"gates": {}, "blocks": {}, "metrics": {}}

    # G2 — health
    h = cli.get("/health")
    out["gates"]["G2_health"] = h.status_code == 200 and h.json() == {"status": "ok"}

    # Canonical pass (first call per query may be a prewarmed hit; that's the product)
    responses, lat = [], []
    for r in rows:
        resp, ms = cli.post("/v1/troubleshoot", {"query": r["original_query"], "siis_response": r["siis_response"]})
        responses.append(resp.json() if resp.status_code == 200 else {})
        lat.append(ms)
    n = len(rows)
    covered = sum(bool(x.get("contexts")) for x in responses)
    valid = sum(not schema_errors(x) for x in responses)
    leaks = sum(len(url_leaks(x)) for x in responses)
