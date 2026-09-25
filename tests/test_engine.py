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


def test_description_is_5_to_7_words():
    for name in ["Force a Restart", "Samsung Authorized Service Centers", "What is Casting?", "Charger Issues",
                 "Touchscreen doesn't work but the screen is still", "Exit", "Attempt to Power On"]:
        d = description(name)
        assert d.startswith("It will") and 5 <= len(words(d)) <= 7, d


def test_deeplinks_resolve_to_the_named_setting():
    by_id = {r["id"]: r for r in KIT}
    msgs = lambda rid: {sg["actionableDeeplink"]["message"]
                        for a in troubleshoot(by_id[rid]["original_query"], by_id[rid]["siis_response"])["contexts"][0]["actions"]
                        for sg in a["stepGroups"] if sg["actionableDeeplink"]}
    assert {"View WiFi Settings", "Open Clear cache in device Settings"} <= msgs("row_1")
    assert "Enable Edge panels" in msgs("row_7")
    assert {"Enable Touch sensitivity", "Disable Touch sensitivity", "View Reset Options"} <= msgs("row_21")


def test_dummy_links_name_the_screen_and_stay_short():
    out = troubleshoot(KIT[0]["original_query"], KIT[0]["siis_response"])
    dummies = [sg["actionableDeeplink"] for a in out["contexts"][0]["actions"] for sg in a["stepGroups"]
               if sg["actionableDeeplink"] and sg["actionableDeeplink"]["deeplink"] == DUMMY]
    assert dummies
    for d in dummies:
        assert 5 <= len(words(d["description"])) <= 7 and 5 <= len(words(d["message"])) <= 7


def test_critical_for_destructive_or_safety_actions():
    out = troubleshoot(UNSEEN[4]["query"], UNSEEN[4]["siis_response"])     # swollen battery
    assert all(a["category"] == "critical" for a in out["contexts"][0]["actions"])


def test_urls_are_stripped():
    siis = {"title": "Reset Wi-Fi", "content": "Go to Settings, tap Connections, and then tap Wi-Fi. "
            "See https://example.com/help or www.samsung.com for details. [link](http://x.y) ![img](a.png)"}
    out = troubleshoot("wifi not working", siis)
    assert out["contexts"] and url_leaks(out) == []
