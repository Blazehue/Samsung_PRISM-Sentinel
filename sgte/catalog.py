"""Deeplink catalogue: semantic matching of step groups to masked deeplinks.

URIs are masked, so matching uses description + message + qna_description.
A match is accepted only when a *specific* on-screen label named in the steps
(e.g. "Clear cache", "Screen timeout") also appears in the catalogue entry —
BM25 alone happily returns plausible-but-wrong links.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .text import BM25, tokens

DATA = Path(__file__).resolve().parent.parent / "data" / "student_kit" / "deeplinks.json"
DUMMY = "bixby://dummy_positive"
