"""Write results.jsonl — one line per kit query: {query, query_variations, response, meta}
(the line shape of the Theme 2 guide's Appendix B).

    python scripts/build_results.py [--out results.jsonl]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import time  # noqa: E402

from sgte.engine import troubleshoot  # noqa: E402
from sgte.variations import variations  # noqa: E402

KIT = ROOT / "data" / "student_kit"
