"""SIIS text → sections → step groups.

Every step is taken verbatim (or split at sentence boundaries) from the SIIS
content — nothing is invented. Explanatory prose is dropped; sections with no
actionable text are skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import URL_PATTERN, strip_urls

VERBS = set("""
tap touch press hold swipe drag pinch slide navigate open go select choose turn switch enable disable toggle
check verify review ensure confirm make try restart reboot power charge plug unplug connect disconnect pair
remove delete clear reset update install uninstall reinstall back restore transfer launch run use set adjust
change move close exit enter sign log add find locate search visit contact call bring take schedule request
wait leave keep avoid allow deny grant follow insert eject replace clean wipe dry scroll view lower increase
decrease activate deactivate download save copy share scan mirror cast rotate calibrate test boot force repeat
continue start stop tap-and-hold long-press re-pair unpair forget reduce lower drag
""".split())

# Softeners/lead-ins stripped (repeatedly) before looking for the verb:
# "Now, please connect…", "Then simply tap…", "You can swipe…".
LEADERS = ("alternatively,", "then,", "then", "next,", "next", "first,", "first", "finally,", "finally",
           "simply", "also,", "also", "now,", "now", "after that,", "once done,", "optionally,", "optionally", "please",
           "you can", "you may", "you should", "you need to", "you will need to", "you'll need to",
           "you must", "just", "again,", "again")

SKIP_PATTERNS = re.compile(
    r"(provided links?|the link(s)? (below|above)|click here|learn more|see (the )?(article|guide)|as shown (below|above)"
    r"|following image|image below|(?:see|in|as shown in) the screenshot|screenshot (?:below|above)|follow (these|the following|the steps below|the steps)\b|^\s*(note|tip|important)\s*:)", re.I)

ADVICE = re.compile(r"\b(recommend(ed)?|should|make sure|ensure|try|contact|visit|check|consider|need to|must)\b", re.I)
HEADER = re.compile(r"^\s*(#{1,4})\s+(.*\S)\s*$")
# "Step 2: Forget the network" on its own line is a heading, not a step.
STEP_HEADER = re.compile(r"^\s*step\s*\d+\s*[:.\-]\s*([^.!?]{3,60})\s*$", re.I)
GROUP_LABEL = re.compile(r"^(to|for|if you want to|when you want to)\b.*:\s*$", re.I)
STEP_PREFIX = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+|step\s*\d+\s*[:.]\s*)", re.I)


@dataclass
class Group:
    label: str
    steps: list[str] = field(default_factory=list)


@dataclass
class Section:
    title: str
    groups: list[Group] = field(default_factory=list)
    text: str = ""

    @property
    def steps(self) -> list[str]:
        return [s for g in self.groups for s in g.steps]


def clean_header(h: str) -> str:
    h = re.sub(r"^(step\s*\d+\s*[:.\-]\s*|\d+\s*[.)]\s*)", "", h.strip(), flags=re.I)
    return h.strip(" :#*").strip()


def _sentences(line: str) -> list[str]:
    # Also split sentences glued without a space: "…pop-up view.Once you've…".
    line = re.sub(r"(?<=[a-z)])\.(?=[A-Z][a-z])", ". ", line.strip())
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'])", line)
    return [p.strip() for p in parts if p.strip()]


def _first_word(s: str) -> str:
    s = s.lower().lstrip("\"'([ ")
    changed = True
    while changed:
        changed = False
        for lead in LEADERS:
            if s.startswith(lead + " "):
                s = s[len(lead) + 1:].lstrip(", ")
                changed = True
                break
    m = re.match(r"[a-z-]+", s)
    return m.group(0) if m else ""


def is_imperative(s: str) -> bool:
    fw = _first_word(s)
    if fw in VERBS:
        return True
    low = s.lower()
    if low.startswith(("note:", "tip:", "important:")):
        return False
    if low.startswith(("do not ", "don't ", "never ")):        # safety instructions
        return True
    # A lead-in clause before a comma: "If X, swipe…", "Using two fingers, swipe…",
    # "In this case, please contact…".
    if "," in s and len(s.split(",", 1)[0].split()) <= 12:
        if _first_word(s.split(",", 1)[1]) in VERBS:
            return True
    return low.startswith(("make sure", "be sure"))


ANCHOR = re.compile(r"<a\b[^>]*>.*?</a>", re.I | re.S)          # link text is a reference, not a step
MD_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\([^)]*\)")            # [text](url) → text
TAG = re.compile(r"</?[a-z][^>]*>", re.I)


def clean_markup(text: str) -> str:
    """HTML/markdown markup → plain text (link targets dropped)."""
    text = ANCHOR.sub(" ", text or "")
    text = MD_LINK.sub(r"\1", text)
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", text, flags=re.I)
    return TAG.sub("", text).replace("&nbsp;", " ").replace("&amp;", "&")


def _normalise(content: str) -> str:
    content = clean_markup(content).replace("\r", "")
    # Headers sometimes follow the category prefix on the same line: "…Tablet): # Title".
    content = re.sub(r"(?<!\n)\s(#{1,4}\s)", r"\n\1", content)
    # Drop the catalogue prefix "Smartphone,Tablet Title ( Smartphone,Tablet): " on line 1.
    first, _, rest = content.partition("\n")
    if re.search(r"\):\s*$", first) or re.match(r"^[A-Z][\w ]*(,[\w ]+)+ .*\(.*\):", first):
        first = re.sub(r"^.*?\):\s*", "", first)
    return (first + "\n" + rest).strip()


def parse_siis(siis: dict) -> tuple[str, list[Section]]:
    title = strip_urls(clean_markup(str(siis.get("title") or ""))).strip()
    content = _normalise(str(siis.get("content") or ""))

    raw_sections: list[tuple[str, list[str]]] = []
    cur_title, cur_lines = title, []
    for line in content.split("\n"):
        m = HEADER.match(line) or STEP_HEADER.match(line)
        if m:
            if cur_lines:
                raw_sections.append((cur_title, cur_lines))
            cur_title, cur_lines = clean_header(m.group(m.lastindex)), []
        elif line.strip():
            cur_lines.append(line.strip())
    if cur_lines:
        raw_sections.append((cur_title, cur_lines))

    sections: list[Section] = []
    for sec_title, lines in raw_sections:
        sec = Section(title=sec_title, text=" ".join(lines))
        group = Group(label="")
        for line in lines:
            line = STEP_PREFIX.sub("", line)
            # A sentence that pointed at a URL is a link reference; dropping only
            # the URL would leave "Visit for more." behind.
            line = " ".join(x for x in _sentences(line) if not URL_PATTERN.search(x))
            if not line or SKIP_PATTERNS.search(line):
                continue
            if GROUP_LABEL.match(line):
                if group.steps:
                    sec.groups.append(group)
                group = Group(label=line.rstrip(":").strip())
                continue
            for sent in _sentences(line):
                if is_imperative(sent) and len(sent.split()) >= 2:
                    step = _tidy(sent)
                    if step not in group.steps:          # same instruction repeated verbatim
                        group.steps.append(step)
        if group.steps:
            sec.groups.append(group)

        if not sec.groups:
            # Prose-only section: keep genuine advice sentences verbatim (e.g.
            # "…it is recommended to contact your email service provider…").
            advice = [_tidy(s) for s in _sentences(sec.text)
                      if ADVICE.search(s) and not SKIP_PATTERNS.search(s) and not URL_PATTERN.search(s)]
            advice = [a for a in advice if 4 <= len(a.split()) <= 45][:3]
            if advice:
                sec.groups.append(Group(label="", steps=advice))
        if sec.groups and not _informational(sec):
            sections.append(sec)
