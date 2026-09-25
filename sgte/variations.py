"""8–10 diverse paraphrases of a user complaint (block A5).

Deterministic: the device, the main symptom and the situation are extracted
from the query and recombined across the registers the Theme 2 guide lists —
formal, casual, keyword-only, frustrated and typo-inclusive — plus question
and support-ticket phrasings. With GEMINI_API_KEY set, an LLM rewrite is
tried first and falls back to this on any failure.
"""
from __future__ import annotations

import re

from .enrich import enrich
from .text import jaccard, tokens
