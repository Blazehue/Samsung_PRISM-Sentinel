"""Smart Guided Troubleshooting Engine — HTTP API.

  GET  /health              → {"status": "ok"}
  POST /v1/troubleshoot     {query, siis_response:{title, content}} → ContextDeeplinkResponse
  POST /v1/variations       {query} → {query, query_variations}
  GET  /v1/metrics          cache hit rate, latency percentiles, cost per query
  GET  /v1/cases            kit + unseen SIIS cases (for the simulator)
  POST /v1/inspect          pipeline internals for one request (enrichment, sections, link decisions)
  GET  /                    the simulator website (web/)

No auth (the judges call it directly). The body is a ContextDeeplinkResponse
plus a "meta" object (latency_ms, cache_hit, model, cost_usd — guide Appendix B)
and, for an empty plan, "fallback": "no_match" | "no_siis_context" (guide §4.2,
§8). The same metadata is mirrored in X-Cache / X-Cache-Hit / X-Latency-Ms /
X-Cost-Usd headers. Extra keys are ignored by the kit's pydantic schema.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from sgte import llm
from sgte.cache import Cache
from sgte.catalog import DUMMY, get_catalog
from sgte.engine import _units, split_interactions, step_group, troubleshoot
from sgte.enrich import enrich
from sgte.parse import parse_siis
from sgte.variations import variations

ROOT = Path(__file__).resolve().parent
KIT = ROOT / "data" / "student_kit" / "siis_responses.json"
UNSEEN = ROOT / "data" / "unseen_siis.json"
WEB = ROOT / "web"
log = logging.getLogger("sgte")
cache = Cache()


class SIIS(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str = ""
    content: str = ""


class TroubleshootRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    query: str | None = ""
    # Tolerate null or a bare string (treated as the article body).
    siis_response: SIIS | str | None = None

    def siis(self) -> dict:
        s = self.siis_response
        if isinstance(s, str):
            return {"title": "", "content": s}
        return (s or SIIS()).model_dump()


class VariationsRequest(BaseModel):
    query: str


def prewarm() -> int:
    """Answer every kit case (and its paraphrases) once so repeats are hits."""
    get_catalog()
    n = 0
    if KIT.exists():
        for r in json.loads(KIT.read_text())["responses"]:
            siis = r["siis_response"]
            resp = troubleshoot(r["original_query"], siis)
            for q in [r["original_query"], *variations(r["original_query"])]:
                cache.store(q, siis, resp)
                n += 1
    return n


@asynccontextmanager
async def lifespan(_: FastAPI):
    n = prewarm()
    log.info("prewarmed %d cache entries", n)
    yield


app = FastAPI(title="Smart Guided Troubleshooting Engine", version="1.0.0", lifespan=lifespan)
# expose_headers: a simulator hosted elsewhere (?api=…) can still read cache/latency.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Cache", "X-Cache-Hit", "X-Latency-Ms", "X-Cost-Usd"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


ENGINE = "sgte-v1"


def _meta(ms: float, hit: bool, ru: llm.RequestUsage) -> dict:
    """Guide §2/[4] and Appendix B: operational metadata with every answer.
    model: the LLM this deployment refines plans with (or the rules-only engine);
    llm_calls: live Gemini calls this request made (0 on cache hits)."""
    model = llm.MODEL if (llm.enabled() or ru.memo_hits) else f"{ENGINE}-deterministic"
    return {"latency_ms": round(ms, 2), "cache_hit": hit, "model": model,
            "cost_usd": round(ru.cost_usd, 6), "llm_calls": ru.calls}


@app.post("/v1/troubleshoot")
def v1_troubleshoot(req: TroubleshootRequest) -> JSONResponse:
    t = time.perf_counter()
    ru = llm.begin_request()
    siis, query = req.siis(), req.query or ""
    if not (siis.get("title", "").strip() or siis.get("content", "").strip()):
        # Guide §5: siis_response omitted → semantic lookup against pre-warmed entries.
        resp, _ = cache.lookup_query(query) if query.strip() else (None, None)
        kind = "semantic" if resp else "miss"
        resp = resp or {"contexts": [], "fallback": "no_siis_context"}
    else:
        resp, kind = cache.lookup(query, siis)
        if resp is None:
            try:
                resp = troubleshoot(query, siis)
            except Exception:                      # never 500 on odd SIIS text
                log.exception("engine failure")
                resp = {"contexts": [], "fallback": "no_match"}
            if resp["contexts"]:
                cache.store(query, siis, resp)
    ms = (time.perf_counter() - t) * 1000
    hit = kind in ("exact", "paraphrase", "semantic")
    cache.record(kind, ms)
    meta = _meta(ms, hit, ru)
    body = {**resp, "meta": meta}
    return JSONResponse(body, headers={"X-Cache": kind, "X-Cache-Hit": str(hit).lower(),
                                       "X-Latency-Ms": f"{ms:.2f}", "X-Cost-Usd": str(meta["cost_usd"])})


@app.post("/v1/variations")
def v1_variations(req: VariationsRequest) -> dict:
    return {"query": req.query, "query_variations": variations(req.query)}


@app.get("/v1/metrics")
def v1_metrics() -> dict[str, Any]:
    return {
        "cache": cache.summary(),
        "llm": {"enabled": llm.enabled(), "model": llm.MODEL, "fallback_models": llm.FALLBACK_MODELS,
                "stages": sorted(llm.STAGES), "memo_entries": len(llm._memo), **llm.usage},
        # Gemini spend so far / requests served (0 on the free tier or when every answer came from cache or memo).
        "cost_per_query_usd": round(llm.usage["cost_usd"] / max(1, cache.summary()["requests"]), 6),
    }


@app.get("/v1/cases")
def v1_cases() -> dict:
    cases = []
    if KIT.exists():
        cases += [{"id": r["id"], "source": "kit", "query": r["original_query"], "siis_response": r["siis_response"]}
                  for r in json.loads(KIT.read_text())["responses"]]
    if UNSEEN.exists():
        cases += [{"id": f"unseen_{i + 1}", "source": "unseen", **c}
                  for i, c in enumerate(json.loads(UNSEEN.read_text())["cases"])]
    para = ROOT / "data" / "paraphrases.json"
    return {"cases": cases, "paraphrases": json.loads(para.read_text())["paraphrases"] if para.exists() else {}}


@app.post("/v1/inspect")
def v1_inspect(req: TroubleshootRequest) -> dict:
    """What each pipeline stage saw — for the simulator's pipeline view. Uses the
    engine's own units, step splitting and link resolver, so it cannot drift."""
    siis, query = req.siis(), req.query or ""
    e = enrich(query)
    cat = get_catalog()
    title, sections = parse_siis(siis)
    out = []
    for sec in sections:
        for name, groups in _units(sec):
            gs = []
            for g in groups:
                steps = [p for st in g.steps for p in split_interactions(st)]
                sg = step_group(name, steps)
                dl = sg["actionableDeeplink"]
                m = cat.match(name, steps) if dl and dl["deeplink"] != DUMMY else None
                gs.append({"label": g.label, "steps": steps, "targets": cat.targets(steps),
                           "link": None if not dl else (
                               {"message": dl["message"], "matched": m.matched_terms if m else [], "id": m.entry.id if m else dl["deeplink"]}
                               if dl["deeplink"] != DUMMY else {"message": "dummy_positive", "screen": cat.primary_screen(steps), "id": DUMMY})})
            out.append({"title": name, "groups": gs})
    plan = troubleshoot(query, siis)
    return {"enriched": {"query": e.raw, "device": e.device, "symptoms": e.symptoms, "is_issue": e.is_issue,
                         "keywords": e.keywords[:16]},
            "siis_title": title, "sections": out, "fallback": plan.get("fallback"),
            "order": [{"actionName": a["actionName"], "category": a["category"]}
                      for g in plan.get("contexts", []) for a in g["actions"]]}
