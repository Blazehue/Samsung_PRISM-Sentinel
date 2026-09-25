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

# (pattern over query/title text, symptom name). Order = priority.
SYMPTOMS: list[tuple[str, str]] = [
    (r"\bcrack(s|ed)?\b|\bshatter|broken glass|\bbleed", "Cracked Screen"),        # not "crackling" audio
    # Feature-specific topics outrank generic symptoms ("Email server not responding").
    (r"\bemail|e-mail|gmail", "Email Connection"),
    (r"\bsmart switch|transfer", "Data Transfer"),
    (r"\bmirror|cast|smart view", "Screen Mirroring"),
    (r"\bmulti ?window|split screen|app pair|edge panel|floating", "Multi Window"),
    (r"\bfingerprint", "Fingerprint Unlock"),
    (r"\b(wet|water|liquid|moisture|spill\w*|rain)\b", "Liquid Damage"),
    (r"\bsim\b|\bsim card", "SIM Card Detection"),
    (r"restart\w* (by )?(it)?self|keeps? (restarting|rebooting)|random\w* (restart|reboot)|restarts? random|boot ?loop", "Random Restarts"),
    (r"keeps? stopping|\bcrash(es|ing|ed)?\b|force clos", "App Crashes"),
    (r"\bnotification", "Notification Delivery"),
    (r"\bbluetooth|earbuds|headphones|buds\b", "Bluetooth Connection"),
    (r"\boverheat|swollen|swell|too hot|really hot|very hot", "Overheating Battery"),
    (r"\bswip\w*\b.*\b(navigation|gesture\w*|direction|sideways|wrong way|up or down)|navigation (bar|gesture\w*)|gesture navigation", "Swipe Navigation"),
    (r"\bflicker|flash|blink", "Screen Flicker"),
    (r"\b(black|blank|dark|white)\b.*\b(screen|display)\b|\b(screen|display)\b.*\b(black|blank|dark)\b|"
     r"\b(went|goes|go|gone|turned|turns|stays|stayed|became) (completely |totally |all )?(black|blank|dark)\b", "Blank Screen"),
    (r"\bnot rotat|rotat|orientation", "Screen Rotation"),
    (r"\btouch ?screen|touch respon|touch\b.*\b(delay|lag)|unresponsive|not respond", "Touchscreen Response"),
    (r"\b(slow|sluggish|laggy|lagging|freez\w*|hang(s|ing)?|stutter\w*)\b", "Slow Performance"),
    (r"\bbattery|charg", "Battery Drain"),
    (r"\bwi-?fi|internet|network", "Network Connection"),
    (r"\bfont|text (size|bigger|smaller)|zoom", "Font Size"),
    (r"\bdistort|lines|green|pink|purple|colou?r", "Display Distortion"),
]
ISSUE_WORDS = re.compile(
    r"\b(not|no|won't|can't|cannot|doesn't|isn't|stopped|issue|problem|error|fail\w*|black|blank|dark|crack\w*|"
    r"flicker\w*|flash\w*|stuck|frozen|freez\w*|lag\w*|delay\w*|slow|broken|distort\w*|unresponsive|"
    r"don't|disconnect\w*|drop\w*|drain\w*|hot|swollen|missing|keeps|"
    # apostrophe-less spellings people actually type, and damage words
    r"wont|cant|doesnt|isnt|dont|didnt|wet|water|liquid|crash\w*|stopping|restarting|rebooting|damage\w*|"
    r"overheat\w*|dead|glitch\w*|bug\w*|faulty|unable|wrong|instead|incorrect\w*|messed|misbehav\w*|weird)\b", re.I)
# "How can I make the text bigger?" asks for a configuration, not a fix.
HOW_TO = re.compile(r"^\s*(how (can|do|to|should) i?|how to|is there a way|i want to|i'd like to|can i|where (is|do))\b", re.I)


@dataclass
class Enriched:
    raw: str
    device: str | None
    symptoms: list[str] = field(default_factory=list)
    is_issue: bool = True
    normalised: str = ""
    keywords: list[str] = field(default_factory=list)


def _clean(q: str) -> str:
    q = re.sub(r"^\s*\d+\.\s*", "", q or "")          # "1. My phone…"
    return re.sub(r"\s+", " ", q.strip().strip("\"'“”")).strip()


def symptoms_of(text: str, by_position: bool = False) -> list[str]:
    """Symptoms named in the text — by table priority (curated titles) or by
    where they first appear (user complaints lead with the main problem)."""
    low = (text or "").lower()
    hits = [(m.start(), i, name) for i, (pat, name) in enumerate(SYMPTOMS) if (m := re.search(pat, low))]
    hits.sort(key=(lambda h: (h[0], h[1])) if by_position else (lambda h: h[1]))
    return [name for _, _, name in hits]


def enrich(query: str) -> Enriched:
    q = _clean(query)
    m = DEVICE.search(q)
    device = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
    syms = symptoms_of(q, by_position=True)
    kw = [t for t in tokens(q) if len(t) > 2]
    normalised = " ".join(dict.fromkeys(kw))
    is_issue = bool(ISSUE_WORDS.search(q)) and not HOW_TO.search(q)
    return Enriched(raw=q, device=device, symptoms=syms, is_issue=is_issue,
                    normalised=normalised, keywords=kw)
