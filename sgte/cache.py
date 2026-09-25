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
