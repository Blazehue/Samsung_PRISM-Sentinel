"""SIIS text → sections → step groups.

Every step is taken verbatim (or split at sentence boundaries) from the SIIS
content — nothing is invented. Explanatory prose is dropped; sections with no
actionable text are skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import URL_PATTERN, strip_urls
