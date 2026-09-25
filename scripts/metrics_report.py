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


# ------------------------------------------------------------------ 2. accuracy
def step_accuracy(pairs):
    """0–3 = completeness + correctness + ordering (each 0–1). No human-labelled
    ground truth ships with the kit (the guide's samples/ folder isn't in it), so:
      completeness — share of the article's UI-interaction clauses present in the plan
      correctness  — share of plan steps found verbatim in the article (grounding)
      ordering     — 1 if actions run auto → manual → critical, else 0"""
    comp, corr, order = [], [], []
    rank = {"auto": 0, "manual": 1, "critical": 2}
    for (q, siis), out in pairs:
        src = clean_markup(siis["content"])
        clauses = [p for s in _sentences(src.replace("\n", ". ")) for p in split_interactions(s) if UI_START.match(p)]
        plan = " ".join(st.lower() for g in out["contexts"] for a in g["actions"] for sg in a["stepGroups"] for st in sg["steps"])
        norm = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
        if clauses:
            comp.append(sum(norm(c) in norm(plan) for c in clauses) / len(clauses))
        ok, tot = grounding_rate(out, siis)
        corr.append(ok / tot if tot else 1.0)
        cats = [rank[a["category"]] for g in out["contexts"] for a in g["actions"]]
        order.append(1.0 if cats == sorted(cats) else 0.0)
    return statistics.mean(comp), statistics.mean(corr), statistics.mean(order)


def catalogue_sweep(matcher):
    """Deeplink relevance 0–2 over every catalogue entry written as a Settings
    step naming its screen: 2 = that entry (or one with the identical on-screen
    message), 1 = same setting but other polarity, or a placeholder naming the
    screen, 0 = a different setting or nothing."""
    scores, lat = [], []
    for e in CAT.entries:
        m = re.match(r"^Opens the (.+?) settings? (?:page )?in ", e.description) or re.match(r"^(?:Enables|Disables) (.+?) via ", e.description)
        lab = m.group(1) if m else re.sub(r"^(View|Enable|Disable|Adjust|Check|Open|Set)\s+", "", e.message)
        lab = lab[0].upper() + lab[1:]
        if e.description.startswith("Retrieves"):
            continue                     # read-only monitor: queried by validation, not opened by a step
        pol = "on" if e.message.startswith("Enable") else "off" if e.message.startswith("Disable") else None
        value = e.message.startswith(("Adjust", "Increase", "Set"))
        step = f"Open Settings, tap {lab}" + (f", and then tap the switch to turn it {pol}." if pol else
                                              ", and then drag the slider to set it." if value else ".")
        got, ms = timed(matcher, [step])
        lat.append(ms)
        if got is None:
            scores.append(0)
        elif got.deeplink == e.deeplink or (got.message == e.message and CAT.desc_label(got) == CAT.desc_label(e)):
            scores.append(2)                        # the entry itself, or a true duplicate of the same page
        elif lab.lower() in (got.message + " " + got.description).lower():
            scores.append(1)
        else:
            scores.append(0)
    return statistics.mean(scores), pct(lat, 95), sum(s == 2 for s in scores) / len(scores), len(scores)


# ------------------------------------------------------------------ ablation matchers
def shipped(steps):
    m = CAT.match("Change the setting", steps)
    return m.entry if m else None


_texts = [f"{e.message} {e.description} {e.qna}" for e in CAT.entries]
_vecs = [embed(t) for t in _texts]


def hybrid_bm25_dense(steps):
    """Variant A: BM25 over the step text + hashed dense-embedding cosine, top-1, no rules."""
    q = tokens(" ".join(steps))
    qv = embed(" ".join(steps))
    top = CAT.bm25.top(q, k=30)
    mx = max((s for _, s in top), default=1) or 1
    best = max(top, key=lambda t: 0.6 * t[1] / mx + 0.4 * cosine(qv, _vecs[t[0]]), default=None)
    return CAT.entries[best[0]] if best and best[1] > 0 else None


def pure_rules(steps):
    """Variant B: exact on-screen label lookup only (no retrieval fallback)."""
    for lab in (CAT._extend(t, steps) for t in CAT.targets(steps)):
        ids = CAT.by_label.get(CAT._norm(lab))
        if ids:
            pol = CAT.polarity(steps)
            cands = [CAT.entries[i] for i in ids]
            return max(cands, key=lambda e: (e.message.startswith(pol), not e.message.startswith("Disable")))
    return None


# ------------------------------------------------------------------ 3/4. latency, cache
def latency_and_cache():
    exact, para_hand, para_gen, cold = [], [], [], []
    hits_hand = hits_gen = 0
    c = Cache()
    for r in KIT:                                   # a cache warmed with the originals only
        c.store(r["original_query"], r["siis_response"], troubleshoot(r["original_query"], r["siis_response"]))
    by_id = {r["id"]: r for r in KIT}
    for _ in range(2):
        for r in KIT:
            (resp, kind), ms = timed(c.lookup, r["original_query"], r["siis_response"])
            exact.append(ms)
    for rid, qs in PARA.items():
        for q in qs:
            (resp, kind), ms = timed(c.lookup, q, by_id[rid]["siis_response"])
            para_hand.append(ms)
            hits_hand += kind != "miss"
    for r in KIT:                                   # generated rewordings are unseen by this cache
        for q in variations(r["original_query"]):
            (resp, kind), ms = timed(c.lookup, q, r["siis_response"])
            para_gen.append(ms)
            hits_gen += kind != "miss"
    for i, (q, s) in enumerate([(r["original_query"], r["siis_response"]) for r in KIT] +
                               [(u["query"], u["siis_response"]) for u in UNSEEN]):
        salted = {"title": s["title"], "content": s["content"] + f"\n{i}{time.time_ns()}"}
        _, ms = timed(troubleshoot, q, salted)
        cold.append(ms)
    return {"exact": exact, "para": para_hand + para_gen, "cold": cold,
            "hit_hand": hits_hand / len(para_hand), "n_hand": len(para_hand),
            "hit_gen": hits_gen / len(para_gen), "n_gen": len(para_gen)}


def gemini_cold(n: int = 30):
    """Cold requests with live Gemini refinement (memo bypassed): latency, calls, tokens."""
    if not llm.enabled():
        return None
    saved = dict(llm._memo)
    llm._memo.clear()
    lat, calls, fails = [], 0, 0
    tin0, tout0, fail0 = llm.usage["input_tokens"], llm.usage["output_tokens"], llm.usage["failures"]
    cases = [(r["original_query"], r["siis_response"]) for r in KIT] + \
            [(u["query"], u["siis_response"]) for u in UNSEEN if u["siis_response"]["title"] not in NO_VIABLE]
    try:
        for i, (q, s) in enumerate(cases[:n]):
            ru = llm.begin_request()
            salted = {"title": s["title"], "content": s["content"] + f"\n{i}{time.time_ns()}"}
            _, ms = timed(troubleshoot, q, salted)
            lat.append(ms)
            calls += ru.calls
    finally:
        llm._memo.clear()
        llm._memo.update(saved)
    tin, tout = llm.usage["input_tokens"] - tin0, llm.usage["output_tokens"] - tout0
    return {"lat": lat, "n": len(lat), "calls": calls, "failures": llm.usage["failures"] - fail0,
            "tin": tin, "tout": tout, "cost": (tin * llm.PRICE_IN + tout * llm.PRICE_OUT) / 1e6}
