"""Optional Gemini layer — language understanding where it helps, never where
correctness is non-negotiable.

Stages (each can be switched off with GEMINI_STAGES):
  understand  — names the topic of an article the symptom lexicon doesn't know,
                and canonicalises a query for the no-article semantic lookup
  rerank      — closed-set deeplink tie-break: picks one of the catalogue
                candidates the rules shortlisted, or "none" (never writes a URI)
  describe    — "It will …" descriptions in plain benefit language
  variations  — 8–10 paraphrases across registers
Steps are never touched: they stay verbatim from the article.

Guardrails: every answer is JSON, validated by the caller's rules; each call
has a time limit and walks a model fallback chain on 404/429/5xx; anything
invalid or late returns None and the deterministic path is used. Results are
memoised by (stage, model, input) in data/llm_cache.json, a persistent cache
(guide Phase 3), so repeats never call Gemini and the committed kit plans are
reproducible with or without a key. The key is read from GEMINI_API_KEY, sent
in a header and never logged.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
FALLBACK_MODELS = [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite").split(",") if m.strip()]
TIMEOUT_S = float(os.getenv("GEMINI_TIMEOUT_S", "2.5"))   # per model; two models fit the 5 s request budget
# USD per 1M tokens. 0 on the AI Studio free tier; set these to your plan's prices.
PRICE_IN = float(os.getenv("GEMINI_PRICE_IN_PER_M", "0"))
PRICE_OUT = float(os.getenv("GEMINI_PRICE_OUT_PER_M", "0"))
STAGES = {s.strip() for s in os.getenv("GEMINI_STAGES", "understand,rerank,describe,variations").split(",") if s.strip()}
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MEMO_FILE = Path(__file__).resolve().parent.parent / "data" / "llm_cache.json"
URLISH = re.compile(r"https?://|www\.|\.com\b|\.html?\b|!\[|<a\s", re.I)

usage = {"calls": 0, "failures": 0, "memo_hits": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
_lock = threading.Lock()


def _load_memo() -> dict:
    try:
        return json.loads(MEMO_FILE.read_text())
    except (OSError, ValueError):
        return {}


_memo: dict = _load_memo()
_dirty = False


@dataclass
class RequestUsage:
    calls: int = 0
    memo_hits: int = 0
    cost_usd: float = 0.0
    models: set = field(default_factory=set)


_request: contextvars.ContextVar[RequestUsage | None] = contextvars.ContextVar("sgte_llm_request", default=None)


def begin_request() -> RequestUsage:
    """Start per-request accounting (read back for the response's meta)."""
    ru = RequestUsage()
    _request.set(ru)
    return ru


def enabled(stage: str | None = None) -> bool:
    """A live call is possible: a key is set and the stage is switched on."""
    return bool(os.getenv("GEMINI_API_KEY")) and (stage is None or stage in STAGES)


def available(stage: str) -> bool:
    """Gemini output can be used: live, or memoised from an earlier call."""
    return stage in STAGES and (enabled(stage) or bool(_memo))


def _memo_key(stage: str, payload) -> str:
    raw = json.dumps([stage, MODEL, payload], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _call(model: str, prompt: str, temperature: float, timeout: float):
    """One HTTP call → (text | None, input tokens, output tokens, status | None)."""
    import httpx
    try:
        r = httpx.post(ENDPOINT.format(model=model),
                       headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"], "content-type": "application/json"},
                       json={"contents": [{"parts": [{"text": prompt}]}],
                             "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"}},
                       timeout=timeout)
    except Exception:
        return None, 0, 0, None                      # timeout / network
    if r.status_code != 200:
        return None, 0, 0, r.status_code
    try:
        data = r.json()
        meta = data.get("usageMetadata", {})
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return text, meta.get("promptTokenCount", 0), meta.get("candidatesTokenCount", 0), 200
    except Exception:
        return None, 0, 0, 200


def ask(stage: str, prompt: str, payload, validate, temperature: float = 0.0, deadline: float | None = None,
        live: bool = True):
    """Memo → live call (model chain, time-boxed) → validate. None means: use
    the deterministic path. live=False only reuses memoised results (cache hits
    must never wait on a model)."""
    global _dirty
    if stage not in STAGES:
        return None
    ru = _request.get()
    key = _memo_key(stage, payload)
    if key in _memo:
        with _lock:
            usage["memo_hits"] += 1
        if ru:
            ru.memo_hits += 1
            ru.models.add(MODEL)
        return _memo[key]
    if not live or not enabled(stage):
        return None
    for model in [MODEL] + [m for m in FALLBACK_MODELS if m != MODEL]:
        remaining = (deadline - time.monotonic()) if deadline else TIMEOUT_S
        if remaining < 0.3:
            break
        text, tin, tout, status = _call(model, prompt, temperature, min(TIMEOUT_S, remaining))
        cost = (tin * PRICE_IN + tout * PRICE_OUT) / 1e6
        with _lock:
            usage["calls"] += 1
            usage["input_tokens"] += tin
            usage["output_tokens"] += tout
            usage["cost_usd"] += cost
        if ru:
            ru.calls += 1
            ru.cost_usd += cost
        if text is None:
            if status in (None, 404, 429, 500, 502, 503, 504):
                continue                             # overloaded / retired / slow: next model
            break
        try:
            out = validate(json.loads(text))
        except Exception:
            out = None
        if out is not None:
            with _lock:
                _memo[key] = out
                _dirty = True
            if ru:
                ru.models.add(model)
            return out
    with _lock:
        usage["failures"] += 1
    return None


def save_memo() -> bool:
    """Persist new Gemini results (used by scripts/warm_llm_cache.py)."""
    global _dirty
    with _lock:
        if not _dirty:
            return False
        MEMO_FILE.write_text(json.dumps(dict(sorted(_memo.items())), indent=1, ensure_ascii=False) + "\n")
        _dirty = False
        return True


# ------------------------------------------------------------------ stages
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


def topic(title: str, head: str, deadline: float | None = None, live: bool = True) -> str | None:
    """2–3-word topic of an article the symptom lexicon doesn't cover."""
    def ok(d):
        t = _clean(d.get("topic", ""))
        return t if 2 <= len(t.split()) <= 3 and re.fullmatch(r"[A-Za-z0-9][\w\- ]*", t) and not URLISH.search(t) else None
    prompt = ("You name troubleshooting topics for Samsung Galaxy support articles. Give the topic of this article in "
              "2 or 3 words, Title Case, naming the feature or symptom (e.g. \"Screen Timeout\", \"Wi-Fi Calling\"). "
              "Return JSON {\"topic\": \"...\"}.\n\nTitle: " + json.dumps(title) + "\nStart of article: " + json.dumps(head[:600]))
    return ask("understand", prompt, {"t": title, "h": head[:600]}, ok, deadline=deadline, live=live)


def canonical(query: str, deadline: float | None = None) -> str | None:
    """Colloquial complaint → a short canonical technical query."""
    def ok(d):
        c = _clean(d.get("canonical", ""))
        return c if 2 <= len(c.split()) <= 20 and not URLISH.search(c) else None
    prompt = ("Rewrite this Samsung Galaxy device complaint as a short canonical technical support query (device "
              "feature + symptom, at most 12 words). Return JSON {\"canonical\": \"...\"}.\n\nComplaint: " + json.dumps(query))
    return ask("understand", prompt, {"q": query}, ok, deadline=deadline)
