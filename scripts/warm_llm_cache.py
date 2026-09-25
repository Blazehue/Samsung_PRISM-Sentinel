"""Fill data/llm_cache.json — the persistent Gemini cache (guide Phase 3:
"persistent local caching with pre-computed query variations").

    python scripts/warm_llm_cache.py        # reads GEMINI_API_KEY from .env or the environment

Runs every kit case (both query wordings), the unseen articles and the
hand-written paraphrases through the engine with Gemini on, then saves what
Gemini returned. Committing the file means the deployed API, local runs and
results.jsonl all give the same answers, and startup makes no burst of calls.
Run it twice if the first pass hit rate limits: cached entries are skipped.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from sgte import llm  # noqa: E402
from sgte.cache import Cache  # noqa: E402
from sgte.engine import troubleshoot  # noqa: E402
from sgte.variations import variations  # noqa: E402

if not llm.enabled():
    sys.exit("GEMINI_API_KEY is not set (put it in .env or the environment)")

DATA = ROOT / "data"
kit = json.loads((DATA / "student_kit" / "siis_responses.json").read_text())["responses"]
inputs = [l.strip() for l in (DATA / "student_kit" / "input.txt").read_text().splitlines() if l.strip()]
unseen = json.loads((DATA / "unseen_siis.json").read_text())["cases"]
para = json.loads((DATA / "paraphrases.json").read_text())["paraphrases"]

cache = Cache()
for r, alt in zip(kit, inputs):
    plan = troubleshoot(r["original_query"], r["siis_response"])
    cache.store(r["original_query"], r["siis_response"], plan)
    troubleshoot(alt, r["siis_response"])
    variations(r["original_query"])
for c in unseen:
    troubleshoot(c["query"], c["siis_response"])
by_id = {r["id"]: r for r in kit}
for rid, qs in para.items():
    for q in qs:
        cache.lookup(q, by_id[rid]["siis_response"])
saved = llm.save_memo()
print(json.dumps({"saved": saved, "memo_entries": len(llm._memo), **llm.usage}, indent=1))
