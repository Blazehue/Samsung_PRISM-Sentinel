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
