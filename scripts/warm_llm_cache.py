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
