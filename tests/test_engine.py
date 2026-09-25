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


def test_markup_and_link_sentences_are_dropped_not_mangled():
    siis = {"title": "Wi-Fi <b>help</b>", "content": '<a href="http://x.com">link</a> Go to Settings, tap Connections, '
            "then tap Wi-Fi. Visit https://samsung.com/support for more. Tap [Advanced](http://a.b) to see options."}
    out = troubleshoot("wifi keeps dropping", siis)
    steps = [s for a in out["contexts"][0]["actions"] for sg in a["stepGroups"] for s in sg["steps"]]
    assert steps == ["Go to Settings.", "Tap Connections.", "Tap Wi-Fi.", "Tap Advanced to see options."]
    assert "<" not in json.dumps(out) and url_leaks(out) == []


def test_garbage_siis_returns_no_contexts():
    assert troubleshoot("123", {"title": "1", "content": "2 3 4"}) == {"contexts": [], "fallback": "no_match"}


def test_how_to_query_is_configuration():
    out = troubleshoot(UNSEEN[5]["query"], UNSEEN[5]["siis_response"])
    assert out["contexts"][0]["goal"].endswith("Configuration")


def test_parser_handles_step_headers():
    _, secs = parse_siis(UNSEEN[2]["siis_response"])
    assert [s.title for s in secs] == ["Restart your router", "Forget the network", "Reset network settings"]


def test_empty_siis_does_not_crash():
    assert troubleshoot("screen black", {"title": "", "content": ""}) == {"contexts": [], "fallback": "no_match"}


def test_variations_count_and_diversity():
    for r in KIT:
        vs = variations(r["original_query"])
        assert 8 <= len(vs) <= 10 and len(set(vs)) == len(vs)
        assert not any(url_leaks(v) for v in vs)


def test_cache_paraphrase_equals_fresh_answer():
    c, r = Cache(), KIT[1]
    c.store(r["original_query"], r["siis_response"], troubleshoot(r["original_query"], r["siis_response"]))
    q = "no text shows, just a blank white display on my S22"
    got, kind = c.lookup(q, r["siis_response"])
    assert kind == "paraphrase" and got == troubleshoot(q, r["siis_response"])
    assert c.lookup("how do I bake bread", r["siis_response"])[1] == "miss"


def test_api_health_and_troubleshoot(client):
    assert client.get("/health").json() == {"status": "ok"}
    r = client.post("/v1/troubleshoot", json={"query": KIT[0]["original_query"], "siis_response": KIT[0]["siis_response"]})
    assert r.status_code == 200 and r.headers["x-cache"] in ("exact", "paraphrase")
    assert format_errors(r.json()) == []
    r = client.post("/v1/troubleshoot", json=UNSEEN[0])
    assert r.status_code == 200 and r.json()["contexts"]


def test_api_tolerates_missing_fields(client):
    for body in ({"query": "how do I bake bread"}, {}, {"query": None, "siis_response": None}):
        r = client.post("/v1/troubleshoot", json=body)
        assert r.status_code == 200 and r.json()["contexts"] == [] and r.json()["fallback"] == "no_siis_context"
    r = client.post("/v1/troubleshoot", json={"query": "wifi", "siis_response": "Go to Settings, tap Connections, then tap Wi-Fi."})
    assert r.status_code == 200 and r.json()["contexts"]


def test_input_txt_phrasing_gets_the_same_answer(client):
    """input.txt drops the '1. ' prefix some original_query values carry."""
    lines = [l.strip() for l in (DATA / "student_kit" / "input.txt").read_text().splitlines() if l.strip()]
    for q, r in zip(lines, KIT):
        got = client.post("/v1/troubleshoot", json={"query": q, "siis_response": r["siis_response"]}).json()
        assert got["contexts"] and strip_meta(got) == troubleshoot(r["original_query"], r["siis_response"])


def test_results_jsonl_shape(tmp_path):
    import subprocess, sys
    out = tmp_path / "results.jsonl"
    root = Path(__file__).resolve().parent.parent
    subprocess.run([sys.executable, str(root / "scripts" / "build_results.py"), "--out", str(out)], check=True)
    lines = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(lines) == len(KIT)
    for l in lines:
        assert set(l) == {"query", "query_variations", "response", "meta"} and 8 <= len(l["query_variations"]) <= 10
        assert set(l["meta"]) == {"latency_ms", "cache_hit", "model", "cost_usd"}


def test_simulator_endpoints(client):
    cases = client.get("/v1/cases").json()
    assert sum(c["source"] == "kit" for c in cases["cases"]) == len(KIT)
    assert sum(c["source"] == "unseen" for c in cases["cases"]) == len(UNSEEN)
    assert cases["paraphrases"]
    insp = client.post("/v1/inspect", json={"query": KIT[0]["original_query"], "siis_response": KIT[0]["siis_response"]}).json()
    assert insp["enriched"]["symptoms"] and insp["sections"]
    # every link in the real plan is one inspect reported (manual actions may drop theirs)
    resp = troubleshoot(KIT[0]["original_query"], KIT[0]["siis_response"])
    real = {sg["actionableDeeplink"]["message"] for a in resp["contexts"][0]["actions"] for sg in a["stepGroups"] if sg["actionableDeeplink"]}
    seen = {g["link"]["message"] for s in insp["sections"] for g in s["groups"] if g["link"]}
    real = {"dummy_positive" if m.startswith("Open ") and m.endswith("device Settings") else m for m in real}
    assert real <= seen and [o["actionName"] for o in insp["order"]] == [a["actionName"] for a in resp["contexts"][0]["actions"]]


def test_site_is_served_without_shadowing_the_api(client):
    page = client.get("/")
    assert page.status_code == 200 and "SGTE" in page.text
    assert client.get("/styles.css").status_code == 200 and client.get("/app.js").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}


# ---------------------------------------------------------------- deeplink matcher regressions
def _link(steps, name="Change the setting"):
    m = get_catalog().match(name, steps)
    return m and m.entry.message


def test_polarity_reads_turn_it_off_and_last_mention():
    assert _link(["Swipe down to open the Quick settings panel and tap Do not disturb to turn it off."]) == "Disable Do not disturb"
    assert _link(["Open Settings, tap Connections, then tap Wi-Fi and turn it on."]) == "Enable WiFi"


def test_exact_label_beats_partial_match():
    assert _link(["Open Settings, tap Connections, and then tap Bluetooth."]) == "View Bluetooth"      # not "Bluetooth scanning"


def test_label_cut_at_and_or_to_is_extended():
    m = get_catalog().match("x", ["Open Settings, and then tap Touch and hold to edit."])
    assert m and "touch and hold to edit" in (m.entry.description + m.entry.message).lower()


def test_ui_chrome_label_on_another_os_gets_no_link():
    steps = ["On your PC, select Start, then begin typing Bluetooth and other device settings and select it when it appears.",
             "If you're using Windows 11, select More options (three dots) next to the device."]
    assert _link(steps) != "View More options"


def test_screenshot_settings_are_not_skipped_as_image_references():
    _, secs = parse_siis({"title": "Screenshots", "content": "Open Settings, tap Advanced features, and then tap Palm swipe to capture screenshot."})
    assert secs and secs[0].steps


def test_whole_catalogue_sweep():
    """Every catalogue entry, phrased as a Settings step naming its screen, links
    back to itself (or an entry with the identical on-screen message)."""
    import re as _re
    cat, ok, wrong = get_catalog(), 0, []
    for e in cat.entries:
        m = _re.match(r"^Opens the (.+?) settings? (?:page )?in ", e.description) or _re.match(r"^(?:Enables|Disables) (.+?) via ", e.description)
        lab = (m.group(1) if m else _re.sub(r"^(View|Enable|Disable|Adjust|Check|Open|Set)\s+", "", e.message))
        lab = lab[0].upper() + lab[1:]
        if e.description.startswith("Retrieves"):
            continue                     # read-only monitor: queried by validation, not opened by a step
        pol = "on" if e.message.startswith("Enable") else "off" if e.message.startswith("Disable") else None
        value = e.message.startswith(("Adjust", "Increase", "Set"))
        step = f"Open Settings, tap {lab}" + (f", and then tap the switch to turn it {pol}." if pol else
                                              ", and then drag the slider to set it." if value else ".")
        got = cat.match("Change the setting", [step])
        same_page = got and cat.desc_label(got.entry) == cat.desc_label(e) and got.entry.message == e.message
        if got and (got.entry.deeplink == e.deeplink or same_page):      # exact entry, or a true duplicate
            ok += 1
        else:
            wrong.append((e.id, lab, got and got.entry.message))
    targets = [e for e in cat.entries if not e.description.startswith("Retrieves")]
    assert ok / len(targets) >= 0.99, (ok, len(targets), wrong)
    assert len(wrong) <= 2, wrong


# ---------------------------------------------------------------- Theme 2 guide (PDF) requirements
import re as _re

ALL_PLANS = [(q, s, troubleshoot(q, s)) for q, s in CASES]


def test_guide_critical_actions_are_last_and_order_is_least_disruptive_first():
    rank = {"auto": 0, "manual": 1, "critical": 2}
    for q, s, out in ALL_PLANS:
        for g in out["contexts"]:
            cats = [rank[a["category"]] for a in g["actions"]]
            assert cats == sorted(cats), (s["title"], [a["category"] for a in g["actions"]])


def test_guide_manual_actions_never_carry_a_deeplink():
    for q, s, out in ALL_PLANS:
        for g in out["contexts"]:
            for a in g["actions"]:
                if a["category"] == "manual":
                    assert not any(sg["actionableDeeplink"] for sg in a["stepGroups"]), a["actionName"]


def test_guide_restart_update_safe_mode_and_reset_are_critical():
    for q, s, out in ALL_PLANS:
        for g in out["contexts"]:
            for a in g["actions"]:
                if _re.search(r"\b(restart|safe mode|factory data reset)\b", a["actionName"], _re.I):
                    assert a["category"] == "critical", a["actionName"]


def test_guide_action_names_title_case_and_titles_sentence_case():
    small = {"a", "an", "the", "and", "or", "but", "of", "on", "in", "to", "for", "with", "by", "at", "from", "as"}
    for q, s, out in ALL_PLANS:
        for g in out["contexts"]:
            t = g["title"].split()
            assert t[0][0].isupper() and all(w.islower() or w.isupper() or not w[1:].islower() or w in ("Samsung", "Galaxy", "Bluetooth", "SIM")
                                             for w in t[1:]), g["title"]
            assert not g["goal"].endswith("."), g["goal"]                      # guide §4.1 exact syntax
            for a in g["actions"]:
                ws = a["actionName"].split()
                for i, w in enumerate(ws):
                    if 0 < i < len(ws) - 1 and w.lower() in small:
                        continue
                    assert w[0].isupper() or not w[0].isalpha(), a["actionName"]


def test_guide_one_interaction_per_step():
    # No step chains two UI interactions ("Go to Settings, tap Display"): count
    # interaction verbs that start a clause.
    starts = _re.compile(r"(?:^|[,;]\s+(?:and\s+)?(?:then\s+)?)(?:tap|select|touch|press|navigate|go to|swipe)\b", _re.I)
    for q, s, out in ALL_PLANS:
        for g in out["contexts"]:
            for a in g["actions"]:
                for sg in a["stepGroups"]:
                    for st in sg["steps"]:
                        assert len(starts.findall(st)) <= 1, st


def test_guide_variation_registers():
    vs = variations("My Galaxy S22 screen turns completely blank when I open Gmail")
    assert any(v.startswith("I am experiencing") for v in vs)                   # formal
    assert any(v.startswith("ugh ") for v in vs)                                 # casual
    assert any(v.endswith("troubleshooting") and "?" not in v for v in vs)       # keyword-only
    assert any("annoying" in v for v in vs)                                      # frustrated
    assert any(_re.search(r"\b(blck|sceren|scren|galxy|seach)\b", v) for v in vs) or any(v.startswith("my ") for v in vs)   # typo-inclusive


def test_guide_no_siis_uses_semantic_lookup_and_meta(client):
    r = client.post("/v1/troubleshoot", json={"query": "My Galaxy S22 screen turns completely blank or white and no text appears"})
    body = r.json()
    assert r.headers["x-cache"] == "semantic" and body["contexts"] and body["contexts"][0]["title"] == "Blank screen"
    assert body["meta"]["cache_hit"] is True and body["meta"]["cost_usd"] == 0.0 and "latency_ms" in body["meta"]
    miss = client.post("/v1/troubleshoot", json={"query": "how do I bake sourdough bread"}).json()
    assert miss["contexts"] == [] and miss["fallback"] == "no_siis_context"
