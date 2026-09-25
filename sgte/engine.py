"""SIIS response + user query → ContextDeeplinkResponse.

Stage 1 (understand): enrich the query and parse the SIIS text into sections
and verbatim step groups.
Stage 2 (compose): one Action per screen/feature (a section, or each labelled
group inside it), one physical interaction per step, deeplinks resolved per
step group, actions ordered least-disruptive first and critical last, then
every field is shaped to the format rules and schema-validated.
"""
from __future__ import annotations

import contextvars
import re
import time
from concurrent.futures import ThreadPoolExecutor

from . import llm
from .catalog import DUMMY, get_catalog
from .enrich import HOW_TO, ISSUE_WORDS, enrich, symptoms_of
from .kit_schema import ContextDeeplinkResponse
from .parse import VERBS, Group, Section, _sentences, _tidy, clean_markup, parse_siis
from .parse import HEADER as MD_HEADER
from .text import STOP, URL_PATTERN, strip_urls, tokens

MAX_ACTIONS = 10

# Guide §4.1 — critical: disruptive or irreversible operations (factory reset,
# restart, firmware update, safe mode…); FAQ — also safety-related. Must be last.
CRITICAL = re.compile(
    r"\b(factory (data )?reset|reset (all|network) settings|erase|wipe|delete all|clear (the )?(app'?s )?data|"
    r"(force |soft )?restart\w*|reboot\w*|safe mode|(software|firmware|system) update\w*|update the software|"
    r"swell\w*|swollen|overheat\w*|smoke|burn\w*|liquid damage|water damage|got wet)\b", re.I)
# Manual escalations (service centre, support, provider) come after self-service manual steps.
ESCALATION = re.compile(r"\b(contact|service cent(er|re)|repair|support|provider|visit)\b", re.I)
RANK = {"auto": 0, "manual": 1, "critical": 3}

SMALL = {"a", "an", "the", "your", "my", "of", "on", "in", "to", "for", "and", "or", "with", "from", "at", "by"}
TRAILING_BAD = SMALL | {"if", "when", "is", "are", "does", "not", "but", "so", "while"}

# First word of a section title → how the description starts ("It will …").
VERB_PHRASE = {
    "check": "check", "verify": "verify", "review": "review", "clear": "clear", "restart": "restart",
    "restarting": "restart", "reboot": "restart", "force": "force", "charge": "charge", "attempt": "attempt to",
    "contact": "help you contact", "use": "help you use", "using": "help you use", "customize": "customize",
    "customise": "customize", "create": "create", "remove": "remove", "exit": "exit", "open": "open",
    "select": "select", "mirror": "mirror", "disconnect": "disconnect", "access": "help you access",
    "adjust": "adjust", "test": "test", "perform": "perform", "update": "update", "transfer": "transfer",
    "enable": "enable", "disable": "disable", "turn": "turn", "reset": "reset", "back": "back up",
    "troubleshooting": "troubleshoot", "fix": "fix", "connect": "connect", "swipe": "use swipe",
    "configure": "configure", "manage": "manage", "set": "set up", "choose": "choose", "change": "change",
}


def _words(s: str) -> list[str]:
    return [w for w in re.split(r"\s+", s.strip()) if w]


def _trim(ws: list[str], n: int) -> list[str]:
    ws = ws[:n]
    while ws and ws[-1].lower().strip(",.") in TRAILING_BAD:
        ws.pop()
    return ws


# ---------------------------------------------------------------- naming
# Where a title stops naming the *thing* and starts describing its state:
# "SIM card not detected" → "SIM Card", "Camera keeps stopping" → "Camera".
STATE_WORDS = {"not", "no", "never", "won't", "wont", "can't", "cant", "doesn't", "doesnt", "isn't", "isnt",
               "is", "are", "was", "keeps", "keep", "stops", "stopped", "fails", "failed", "won", "does", "has"}


def _unshout(text: str) -> str:
    """'DARK MODE' → 'Dark Mode'; short acronyms (SIM, USB, PC) stay."""
    return re.sub(r"\b[A-Z]{4,}\b", lambda m: m.group(0).capitalize(), text)


def goal_name(siis_title: str, query: str, head: str = "", deadline: float | None = None, live: bool = True) -> str:
    syms = symptoms_of(siis_title) or symptoms_of(query, by_position=True)
    if syms:
        return syms[0]
    # Unknown topic: Gemini names it from the article (not the query, so the
    # name is cache-stable); validated to 2–3 plain words, else the rules below.
    if llm.available("understand") and (siis_title or head):
        named = llm.topic(siis_title, head, deadline=deadline, live=live)
        if named:
            return title_case(named)
    ws = re.findall(r"[A-Za-z][\w'-]*", _unshout(siis_title))
    # "What are Bixby Routines?" → "Bixby Routines"; "Change the screen timeout" → "screen timeout"
    if ws and ws[0].lower() in {"what", "how", "why", "when", "where", "which", "who"}:
        ws = ws[1:]
        while ws and ws[0].lower() in STATE_WORDS | {"do", "can", "to", "should", "i", "you"}:
            ws = ws[1:]
    while ws and ws[0].lower() in VERBS:
        ws = ws[1:]
    for k, w in enumerate(ws):
        if w.lower() in STATE_WORDS:
            ws = ws[:k]
            break
    ws = [w for w in ws if w.lower() not in STOP and w.lower() not in SMALL]
    ws = _trim(ws, 3) or ["Device", "Support"]
    if len(ws) == 1:
        ws.append("Issue")
    return " ".join(w[0].upper() + w[1:] for w in ws)


TC_SMALL = {"a", "an", "the", "and", "or", "but", "nor", "of", "on", "in", "to", "for", "with", "by", "at",
            "from", "as", "vs", "via", "per", "into"}
KEEP_CASE = {"wi-fi": "Wi-Fi", "smartthings": "SmartThings", "smart": "Smart", "samsung": "Samsung",
             "galaxy": "Galaxy", "bluetooth": "Bluetooth", "sim": "SIM", "pc": "PC", "tv": "TV", "usb": "USB"}


def _keep(w: str) -> bool:
    """Acronyms and brand spellings keep their casing (PC, SIM, Wi-Fi, SmartThings)."""
    core = w.strip("'\".,:;!?()")
    return (core.isupper() and len(core) <= 4) or bool(re.search(r"[a-z][A-Z]", core))


def title_case(text: str) -> str:
    """Guide §4.1: actionName in Title Case — 'Use pop-up view' → 'Use Pop-Up View'."""
    out = []
    for i, w in enumerate(_words(text)):
        low = w.lower()
        if low in KEEP_CASE:
            out.append(KEEP_CASE[low])
        elif _keep(w):
            out.append(w)
        elif 0 < i < len(_words(text)) - 1 and low in TC_SMALL:      # first and last word always capitalised
            out.append(low)
        else:
            out.append("-".join(p[:1].upper() + p[1:] for p in w.split("-")))
    return " ".join(out)


def sentence_case(text: str) -> str:
    """Guide §4.1: title in sentence case — 'Email Connection' → 'Email connection'."""
    out = []
    for i, w in enumerate(_words(text)):
        low = w.lower()
        if low in KEEP_CASE:
            out.append(KEEP_CASE[low])
        elif _keep(w):
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:].lower() if i == 0 else low)
    return " ".join(out)


def action_name(sec: Section) -> str:
    name = _unshout(re.sub(r"\s+", " ", strip_urls(sec.title)).strip(" .:#")) or "Follow Recommended Steps"
    ws = _words(name)
    return title_case(" ".join(_trim(ws, 8)) if len(ws) > 8 else name)


def label_name(label: str) -> str:
    """Group label → action name: "To clear the app's cache" → "Clear the App's Cache"."""
    t = re.sub(r"^(if you want to|when you want to|to|for)\s+", "", label.strip().rstrip(":"), flags=re.I)
    return title_case(t) if t else ""


PROPER = {"samsung", "galaxy", "smartthings", "wi-fi", "bluetooth", "google"}
PHRASES = re.compile(r"\b(smart view|smart switch|edge panels?|apps edge|secure folder)\b", re.I)
NOUNISH = {"touch", "view", "power", "set", "screen", "display", "call", "scan", "test", "update", "download"}
ISSUE_NOUNS = {"issues", "issue", "problems", "problem"}
PROBLEM_NOUNS = ISSUE_NOUNS | {"crashes", "restarts", "damage", "errors", "failure", "flicker"}   # no "… issues" after these


def _case(w: str) -> str:
    if w.isupper() or w.lower() in PROPER or (len(w) > 1 and w[1:].lower() != w[1:]):
        return w[0].upper() + w[1:] if w.lower() in PROPER else w
    return w.lower()


def description(name: str) -> str:
    """'It will …', 5–7 words, from the action name."""
    ws = [w.strip("?:.,!") for w in _words(name)]
    ws = [w for w in ws if w]
    if not ws:
        return "It will guide you through the steps"
    first = ws[0].lower()
    if first in VERB_PHRASE or (first in VERBS and first not in NOUNISH):
        verb, obj = _words(VERB_PHRASE.get(first, first)), ws[1:]
        if first == "turn" and obj and obj[0].lower() in ("on", "off"):
            verb, obj = verb + [obj[0].lower()], obj[1:]
        if obj and obj[0].lower() == verb[-1]:          # "attempt to To…", "back up Up…"
            obj = obj[1:]
    elif any(w.lower() in ISSUE_NOUNS for w in ws):
        verb, obj = ["help", "resolve"], [w for w in ws if w.lower() not in ISSUE_NOUNS] + ["issues"]
    elif name.strip().endswith("?"):
        verb, obj = ["explain"], ws
    else:
        verb, obj = ["cover"], ws
    obj = [_case(w) for w in obj]
    room = 7 - 2 - len(verb)
    if len(obj) > room:                       # articles/possessives go first
        obj = [w for w in obj if w.lower() not in {"a", "an", "the", "your", "my"}]
    keep = obj[:room]
    obj = _trim(obj, room)
    # "power on" / "turn off": the particle belongs to the verb, keep it.
    if len(keep) > len(obj) and keep[len(obj)].lower() in ("on", "off") and obj and obj[-1].lower() in ("power", "turn", "switch"):
        obj.append(keep[len(obj)].lower())
    out = ["It", "will"] + verb + obj
    if len(out) < 5:
        tail = ["on", "your", "device"] if len(out) <= 4 and "device" not in (w.lower() for w in obj) else ["now"]
        out += tail[: 7 - len(out)]
    while len(out) < 5:
        out.append("safely")
    return PHRASES.sub(lambda m: m.group(0).title(), " ".join(out))


# ---------------------------------------------------------------- steps
UI_VERB = r"(?:tap|select|touch|press|open|swipe|navigate|go|choose|scroll|enter|toggle|turn|drag|search|find)"
DANGLING = {"for", "to", "and", "or", "the", "a", "an", "on", "in", "with", "of", "from", "by"}
SPLIT = r",?\s+(?:and\s+)?then\s+|;\s+|,\s+(?:and\s+)?(?=" + UI_VERB + r"\b)|\s+and\s+(?=(?:tap|select|press|turn)\b)"
SPLIT_KEEP = re.compile("(" + SPLIT + ")", re.I)          # capturing: separators come back verbatim


def _finish(p: str) -> str:
    p = p.strip().rstrip(",;:")
    p = p[:1].upper() + p[1:]
    return p if p.endswith((".", "!", "?")) else p + "."


def split_interactions(step: str) -> list[str]:
    """Guide §4.1 — one physical interaction per step:
    "Navigate to Settings, tap Display, and then tap Screen timeout." →
    "Navigate to Settings." / "Tap Display." / "Tap Screen timeout."
    Separators are kept verbatim when a piece has to be re-attached ("enter"
    alone is not an interaction), so every piece stays a substring of the source."""
    from .parse import is_imperative
    # A piece is an interaction if it's an instruction of ≥ 2 words that doesn't
    # dangle ("search for" + "and select X" → "Search for and select X").
    ok = lambda p: is_imperative(p) and len(p.split()) >= 2 and p.split()[-1].lower() not in DANGLING
    bits = SPLIT_KEEP.split(step.rstrip("."))
    pieces, seps = bits[0::2], bits[1::2] + [""]
    out, carry = [], ""
    for piece, sep in zip(pieces, seps):
        cur = carry + piece
        if ok(cur):
            out.append(cur)
            carry = ""
        else:
            carry = cur + sep        # "enter" + " and " → joins the next piece
    if carry.strip():
        if out:
            out[-1] = out[-1] + seps[-2] + carry if len(seps) > 1 else out[-1] + carry
        else:
            out.append(carry)
    out = [p for p in out if p.strip()]
    return [_finish(p) for p in out] if len(out) > 1 else [step]


# ---------------------------------------------------------------- deeplinks
def _dummy(screen: str) -> dict:
    sw = _trim(_words(screen), 3)
    return {
        "deeplink": DUMMY,
        "description": " ".join(["Opens", "the", *sw, "settings", "screen"]),
        "message": " ".join(["Open", *sw, "in", "device", "Settings"]),
        "originalType": "placeholder",
    }


def _validation(v: dict | None) -> dict | None:
    if not v:
        return None
    out = {"deeplink": v["deeplink"], "key": str(v["key"])}
    for k in ("resultType", "condition"):
        if v.get(k) is not None:
            out[k] = v[k]
    if v.get("value") is not None:
        out["value"] = str(v["value"])
    return out


def step_group(name: str, steps: list[str], link: bool = True) -> dict:
    cat = get_catalog()
    sg: dict = {"steps": steps, "validationDeeplink": None, "actionableDeeplink": None}
    if not link:
        return sg
    m = cat.match(name, steps)
    if m:
        e = m.entry
        sg["actionableDeeplink"] = {"deeplink": e.deeplink, "description": e.description,
                                    "message": e.message, "originalType": e.original_type}
        sg["validationDeeplink"] = _validation(e.validation)
    elif cat.mentions_settings(steps) and re.search(r"\bsettings\b", " ".join(steps), re.I):
        screen = cat.primary_screen(steps)
        if screen:
            sg["actionableDeeplink"] = _dummy(screen)
    return sg


# ---------------------------------------------------------------- assembly
def _score(query_toks: set, siis_toks: set, sym_agree: bool) -> float:
    if not query_toks:
        return 0.7
    cov = len(query_toks & siis_toks) / len(query_toks)
    s = 0.55 + 0.35 * cov + (0.08 if sym_agree else 0.0)
    return round(min(0.99, max(0.05, s)), 2)


def _whole_doc_desc(gname: str, issue: bool) -> str:
    """Description for an untitled article's single action, named after the goal.
    Longest template that still fits the 5–7-word rule for a 2–3-word name."""
    name = [_case(w) for w in _words(gname)]
    templates = ([["help", "resolve"], ["resolve"]], ) if issue else ([["help", "you", "configure"], ["configure"]], )
    for verb in templates[0]:
        out = ["It", "will", *verb, *name] + (["issues"] if issue and name[-1].lower() not in PROBLEM_NOUNS else [])
        if 5 <= len(out) <= 7:
            return PHRASES.sub(lambda m: m.group(0).title(), " ".join(out))
    return description(gname)
