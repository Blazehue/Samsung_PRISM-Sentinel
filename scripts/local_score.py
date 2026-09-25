"""Local mirror of the Theme 2 gates (G2–G5) and automated blocks (A1–A5).

    python scripts/local_score.py                 # in-process (FastAPI TestClient)
    python scripts/local_score.py --url http://host:8000   # against a live deployment
    python scripts/local_score.py --json out.json # also write the numbers

Thresholds are the FAQ's; the point totals are our own estimate of how the
official scorer weights each block, for tracking regressions.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
