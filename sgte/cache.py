"""Two-tier fast-path cache (block A3).

Tier 1 — exact: same normalised query + same SIIS → the stored response.
Tier 2 — paraphrase: same SIIS, different wording. Everything expensive in a
response (parsing, step grouping, deeplink resolution) depends only on the
SIIS text, so the cached plan is reused and just the query-dependent goal
fields (name, kind, score) are recomputed for the new phrasing. A query that
shares no content word with the SIIS or with any cached phrasing is treated
as off-topic and goes through the full engine.
"""
from __future__ import annotations

import copy
import hashlib
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from . import llm
from .engine import retarget
from .enrich import enrich
from .text import cosine, embed, tokens


def siis_key(siis: dict) -> str:
    blob = f"{(siis or {}).get('title', '')}\x00{(siis or {}).get('content', '')}"
    return hashlib.sha256(" ".join(blob.split()).lower().encode()).hexdigest()[:24]


@dataclass
class _Bucket:
    siis_toks: set
    plan: dict
    siis: dict = field(default_factory=dict)
    responses: dict = field(default_factory=dict)       # normalised query → response
    query_toks: set = field(default_factory=set)


class Cache:
    def __init__(self, max_siis: int = 2048, max_per_siis: int = 64):
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._max_siis, self._max_per = max_siis, max_per_siis
        self._lock = threading.Lock()
        self.stats = {"exact": 0, "paraphrase": 0, "miss": 0}
        self.latencies: dict[str, deque] = {k: deque(maxlen=5000) for k in ("hit", "miss")}

    def lookup(self, query: str, siis: dict) -> tuple[dict | None, str]:
        e = enrich(query)
        key = siis_key(siis)
        with self._lock:
            b = self._buckets.get(key)
            if b is not None:
                self._buckets.move_to_end(key)
                if e.normalised in b.responses:
                    self.stats["exact"] += 1
                    return copy.deepcopy(b.responses[e.normalised]), "exact"
                kw = set(e.keywords)
                if kw & (b.siis_toks | b.query_toks):
                    self.stats["paraphrase"] += 1
                    plan = copy.deepcopy(b.plan)
                    return retarget(plan, query, siis), "paraphrase"
            self.stats["miss"] += 1
            return None, "miss"
