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
