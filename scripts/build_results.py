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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "results.jsonl"))
    args = ap.parse_args()

    rows = json.loads((KIT / "siis_responses.json").read_text())["responses"]
    with open(args.out, "w") as f:
        for r in rows:
            t = time.perf_counter()
            response = troubleshoot(r["original_query"], r["siis_response"])
            ms = (time.perf_counter() - t) * 1000
            line = {
                "query": r["original_query"],
                "query_variations": variations(r["original_query"]),
                "response": response,
                "meta": {"latency_ms": round(ms, 2), "cache_hit": False, "model": "sgte-deterministic-v1", "cost_usd": 0.0},
            }
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} lines → {args.out}")


if __name__ == "__main__":
    main()
