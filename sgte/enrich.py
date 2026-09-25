"""Query enrichment: raw user complaint → device, symptoms, normalised query.

Deterministic so the same complaint always yields the same key (cache) and the
same goal name.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import tokens

DEVICE = re.compile(
    r"\b((?:samsung\s+)?galaxy\s+(?:z\s+)?(?:flip|fold|tab|note|[a-z])\s*\d*\w*(?:\s+(?:ultra|plus|fe|\+))?"
    r"|samsung\s+[a-z]\d{2,4}\w*|\b[a-z]\d{3}[a-z]?\b)", re.I)
