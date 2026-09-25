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
    out["gates"]["G3_coverage"] = f"{covered}/{n} ({covered / n:.0%}) — need ≥95%"
    out["gates"]["G4_schema_valid"] = f"{valid}/{n} ({valid / n:.0%}) — need ≥90%"
    out["gates"]["G5_url_leaks"] = f"{leaks} — need 0"
    gates_ok = out["gates"]["G2_health"] and covered / n >= 0.95 and valid / n >= 0.9 and leaks == 0

    # A1 — format rules
    fmt = [format_errors(x) for x in responses]
    a1 = sum(not e for e in fmt) / n
    out["blocks"]["A1_format"] = {"clean_responses": f"{a1:.0%}", "points": round(15 * a1, 1),
                                  "errors": [e for es in fmt for e in es][:10]}

    # A2 — deeplink validity + coverage
    links, bad_links, groups, linked, auto_ok, autos = 0, 0, 0, 0, 0, 0
    for x in responses:
        for g in x.get("contexts", []):
            for a in g["actions"]:
                if a.get("category") == "auto":
                    autos += 1
                    auto_ok += all(sg.get("actionableDeeplink") for sg in a["stepGroups"])
                for sg in a["stepGroups"]:
                    groups += 1
                    for k in ("actionableDeeplink", "validationDeeplink"):
                        if sg.get(k):
                            links += 1
                            bad_links += sg[k]["deeplink"] not in uris
                    linked += bool(sg.get("actionableDeeplink"))
    validity = 1 - bad_links / links if links else 1.0
    auto_rate = auto_ok / autos if autos else 1.0
    out["blocks"]["A2_deeplinks"] = {"links": links, "valid": f"{validity:.0%}", "auto_with_link": f"{auto_rate:.0%}",
                                     "stepgroups_linked": f"{linked}/{groups}",
                                     "points": round(15 * (0.6 * validity + 0.4 * auto_rate), 1)}

    # A3 — cache: repeats, paraphrases, cold
    rep = []
    for _ in range(3):
        for r in rows:
            resp, ms = cli.post("/v1/troubleshoot", {"query": r["original_query"], "siis_response": r["siis_response"]})
            rep.append((ms, resp.headers.get("x-cache", "miss") != "miss"))
    # Hand-written paraphrases, never pre-warmed (our own variations would be exact hits).
    para, by_id = [], {r["id"]: r for r in rows}
    for rid, qs in json.loads(PARA.read_text())["paraphrases"].items():
        for q in qs:
            resp, ms = cli.post("/v1/troubleshoot", {"query": q, "siis_response": by_id[rid]["siis_response"]})
            para.append(resp.headers.get("x-cache", "miss") != "miss")
    cold = []
    for c in unseen:
        salted = {"title": c["siis_response"]["title"],
                  "content": c["siis_response"]["content"] + f"\n{time.time_ns()}"}
        cold.append(cli.post("/v1/troubleshoot", {"query": c["query"], "siis_response": salted})[1])
    rep_p95, rep_hit = p95([m for m, _ in rep]), sum(h for _, h in rep) / len(rep)
    para_hit, cold_p95 = sum(para) / len(para), p95(cold)
    a3 = (5 * (rep_p95 <= 300 and rep_hit >= 0.9) + 5 * (para_hit >= 0.8) + 5 * (cold_p95 <= 8000))
    out["blocks"]["A3_cache"] = {"repeat_p95_ms": round(rep_p95, 1), "repeat_hit": f"{rep_hit:.0%}",
                                 "paraphrase_hit": f"{para_hit:.0%}", "cold_p95_ms": round(cold_p95, 1), "points": a3}

    # A4 — unseen SIIS: format-clean and grounded
    ok, g_ok, g_all = 0, 0, 0
    for c in unseen:
        resp = cli.post("/v1/troubleshoot", c)[0].json()
        if c["siis_response"]["title"] in NO_VIABLE:          # explainer only → guide §4.2 no_match is correct
            ok += resp.get("contexts") == [] and resp.get("fallback") == "no_match"
            continue
        ok += bool(resp.get("contexts")) and not format_errors(resp, uris)
        a, b = grounding_rate(resp, c["siis_response"])
        g_ok, g_all = g_ok + a, g_all + b
    a4 = ok / len(unseen) * (g_ok / g_all if g_all else 0)
    out["blocks"]["A4_generalisation"] = {"clean": f"{ok}/{len(unseen)}", "grounded_steps": f"{g_ok}/{g_all}",
                                          "points": round(10 * a4, 1)}

    # A5 — variations: 8–10, distinct from each other and the query
    counts, sims = [], []
    for r in rows:
        vs = cli.post("/v1/variations", {"query": r["original_query"]})[0].json()["query_variations"]
        counts.append(8 <= len(vs) <= 10)
        ts = [set(tokens(v)) for v in vs]
        sims += [jaccard(a, b) for i, a in enumerate(ts) for b in ts[i + 1:]]
    in_range = sum(counts) / len(counts)
    mean_sim = statistics.mean(sims) if sims else 1
    out["blocks"]["A5_variations"] = {"8_to_10": f"{in_range:.0%}", "mean_pairwise_jaccard": round(mean_sim, 3),
                                      "points": round(5 * in_range * (1 if mean_sim < 0.5 else 0.5), 1)}

    # Product metrics (brochure)
    g_ok = g_all = 0
    for r, x in zip(rows, responses):
        a, b = grounding_rate(x, r["siis_response"])
        g_ok, g_all = g_ok + a, g_all + b
    out["metrics"] = {"step_grounding": f"{g_ok}/{g_all} ({g_ok / g_all:.1%})",
                      "canonical_p50_ms": round(statistics.median(lat), 1), "canonical_p95_ms": round(p95(lat), 1),
                      "server": cli.get("/v1/metrics").json()}

    total = sum(b["points"] for b in out["blocks"].values())
    out["gates_pass"] = gates_ok
    out["automated_points"] = f"{total:.1f}/60"
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
