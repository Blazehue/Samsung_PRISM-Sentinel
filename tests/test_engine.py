import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
from sgte.cache import Cache
from sgte.catalog import DUMMY, get_catalog
from sgte.engine import description, troubleshoot
from sgte.grounding import grounding_rate
from sgte.parse import parse_siis
from sgte.rules import format_errors, url_leaks, words
from sgte.variations import variations

DATA = Path(__file__).resolve().parent.parent / "data"
KIT = json.loads((DATA / "student_kit" / "siis_responses.json").read_text())["responses"]
UNSEEN = json.loads((DATA / "unseen_siis.json").read_text())["cases"]
CASES = [(r["original_query"], r["siis_response"]) for r in KIT] + [(c["query"], c["siis_response"]) for c in UNSEEN]
# Guide §4.2: an article with no viable instructions yields contexts [] + fallback "no_match".
NO_VIABLE = {"What are Bixby Routines?"}
strip_meta = lambda body: {k: v for k, v in body.items() if k != "meta"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app_module.app) as c:
        yield c


@pytest.mark.parametrize("query,siis", CASES)
def test_every_case_is_format_clean_and_grounded(query, siis):
    out = troubleshoot(query, siis)
    if siis["title"] in NO_VIABLE:
        assert out == {"contexts": [], "fallback": "no_match"}
        return
    assert out["contexts"], "no contexts"
    assert format_errors(out, get_catalog().uris) == []
    ok, total = grounding_rate(out, siis)
    assert total and ok == total, "a step is not verbatim from the SIIS text"
