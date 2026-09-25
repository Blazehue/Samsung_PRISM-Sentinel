"""Deeplink catalogue: semantic matching of step groups to masked deeplinks.

URIs are masked, so matching uses description + message + qna_description.
A match is accepted only when a *specific* on-screen label named in the steps
(e.g. "Clear cache", "Screen timeout") also appears in the catalogue entry —
BM25 alone happily returns plausible-but-wrong links.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .text import BM25, tokens

DATA = Path(__file__).resolve().parent.parent / "data" / "student_kit" / "deeplinks.json"
DUMMY = "bixby://dummy_positive"

# Words that name *where* you are, not *what* you change — never enough to justify a link.
GENERIC = set(tokens(
    "settings setting quick panel menu screen icon button option options app apps page home tap select "
    "open navigate go device more feature features general advanced top bottom right left side switch toggle "
    "view power button enable disable turn on off show use issue issues problem problems step steps check "
    "mode add adjust now access set change remove new start done ok yes allow confirm restart try"
))

TARGET = re.compile(
    r"\b(?i:tap|touch|select|choose|open|enable|disable|turn on|turn off|toggle|go to|navigate to|find|search for)\s+"
    r"(?:on\s+)?(?:the\s+)?([A-Z0-9][\w\-'/&+ ]{1,60}?)(?=\s*(?:[,.;:(]|\band\b|\bthen\b|\bto\b|\bwhen\b|\bif\b|\bnext\b|$))"
)
SETTINGS_PATH = re.compile(r"Settings\s*>\s*([^.,;]+)")
# "tap the switch next to Touch sensitivity", "the Auto rotate toggle"
SWITCH_NEXT = re.compile(r"(?i:switch(?:es)?|toggle|slider)\s+(?i:next to|beside|for)\s+([A-Z][\w\-' ]{1,45}?)(?=\s*(?:[,.;:(]|\band\b|\bor\b|\bto\b|$))")
# "turn off", "turn it off", "switch the Wi-Fi off", "disable it" … — whichever is mentioned last wins.
_OBJ = r"(?:\s+(?:it|this|that|them|this feature|the [\w-]+(?: [\w-]+)?))?"
OFF = re.compile(r"\b(?:turn|switch|toggle)" + _OBJ + r"\s+off\b|\bdisable\b|\bdeactivate\b", re.I)
ON = re.compile(r"\b(?:turn|switch|toggle)" + _OBJ + r"\s+on\b|\benable\b|\bactivate\b|\btap the switch(?:es)?\b", re.I)
# "Drag the slider…", "choose a longer time", "set it to 30 seconds": the step sets a value.
ADJUST = re.compile(r"\b(?:drag|slide|move) the slider|\badjust the (?:level|size|value|brightness|volume)\b|"
                    r"\bchoose a (?:longer|shorter|higher|lower|different)\b|\bset (?:it|the [\w ]{1,20}) to\b", re.I)
VERB_PREFIX = re.compile(r"^(?:View|Enable|Disable|Adjust|Check|Open|Set|Switch|Increase|Diagnose|Optimize)\s+", re.I)
DESC_LABEL = [re.compile(p) for p in (r"^Opens the (.+?) settings? (?:page )?in ", r"^Opens the (.+?) (?:page|screen|settings) ",
                                         r"^(?:Enables|Disables) (.+?) via ", r"^Opens (?:the )?(.+?) (?:in|via) ")]

# Words that name UI furniture, not a setting — never enough on their own.
CHROME = set(tokens("more options option menu settings setting button buttons icon home back page tab ok done next "
                    "cancel apply save all general advanced other show view"))

# Confirmation buttons are where a flow *ends*, not the screen it is about.
BUTTONS = {"delete all", "delete", "reset", "ok", "restart", "confirm", "done", "allow", "start", "start now",
           "yes", "no", "cancel", "apply", "save", "disconnect", "remove", "erase", "next", "continue",
           "turn off", "power off", "reset settings", "remove device", "add device", "unpair", "pair", "forget",
           "install", "download and install", "update", "unrestricted", "uninstall", "force stop"}


@dataclass
class Entry:
    id: str
    deeplink: str
    description: str
    message: str
    original_type: str | None
    qna: str
    validation: dict | None
    toks: set


@dataclass
class Match:
    entry: Entry
    score: float
    matched_terms: list[str]


class Catalog:
    def __init__(self, path: Path = DATA):
        raw = json.loads(Path(path).read_text())["deeplinks"]
        self.entries: list[Entry] = []
        docs = []
        for e in raw:
            if e["deeplink"] == DUMMY:
                continue
            text = f"{e.get('message','')} {e.get('message','')} {e.get('description','')} {e.get('qna_description','')}"
            toks = tokens(text)
            self.entries.append(Entry(
                id=e["id"], deeplink=e["deeplink"], description=e.get("description") or "",
                message=e.get("message") or "", original_type=e.get("originalType"),
                qna=e.get("qna_description") or "", validation=e.get("validation"), toks=set(toks),
            ))
            docs.append(toks)
        self.bm25 = BM25(docs)
        # Exact on-screen label → entries. "View Bluetooth" and the description's
        # "Opens the Bluetooth settings page…" both give the label "bluetooth".
        self.by_label: dict[str, list[int]] = {}
        for i, e in enumerate(self.entries):
            for lab in self.labels_of(e):
                self.by_label.setdefault(lab, []).append(i)
        self.uris = ({e.deeplink for e in self.entries} | {DUMMY}
                     | {e.validation["deeplink"] for e in self.entries if e.validation})

    # ------------------------------------------------------------------ helpers
    @classmethod
    def desc_label(cls, e: "Entry") -> str:
        """The page the description names: "Opens the Bluetooth settings page…" → "bluetooth"."""
        for pat in DESC_LABEL:
            m = pat.match(e.description)
            if m:
                return cls._norm(m.group(1))
        return ""

    @classmethod
    def labels_of(cls, e: "Entry") -> set[str]:
        labs = {cls._norm(VERB_PREFIX.sub("", e.message)), cls.desc_label(e)}
        return {l for l in labs if l.strip()}

    def _extend(self, label: str, steps: list[str]) -> str:
        """A label the target regex cut short at "and"/"to"/"(" — "Touch" from
        "tap Touch and hold to edit" — is extended to the longest continuation
        that is exactly a catalogue label."""
        for s in steps:
            # every occurrence — in "Tap Tap to click" the first "Tap" is the verb
            for k in (m.start() for m in re.finditer(re.escape(label), s)):
                rest = re.split(r"[,.;:]", s[k:], maxsplit=1)[0]
                ws = rest.split()
                for n in range(len(ws), len(label.split()), -1):
                    cand = " ".join(ws[:n])
                    if self._norm(cand) in self.by_label:
                        return cand
        return label

    @staticmethod
    def polarity(steps: list[str]) -> str:
        """Enable / Disable (last on/off mentioned wins), Adjust (the step sets a
        value), or View (the step only opens the page)."""
        blob = " ".join(steps)
        hits = [(m.start(), "Disable") for m in OFF.finditer(blob)] + [(m.start(), "Enable") for m in ON.finditer(blob)]
        if hits:
            return max(hits)[1]
        return "Adjust" if ADJUST.search(blob) else "View"

    @staticmethod
    def fits(e: "Entry", polarity: str) -> bool:
        """Does the entry do what the step does? Adjust covers Increase / Set."""
        if polarity == "Adjust":
            return e.message.startswith(("Adjust", "Increase", "Set"))
        return e.message.startswith(polarity)

    @staticmethod
    def targets(steps: list[str], known: dict | None = None, extend=None) -> list[str]:
        """On-screen labels named by the steps, most specific (last) first.
        A label that looks like a button ("Allow…", "Unpair") is skipped unless
        it is, in full, a setting the catalogue names (`known`, after `extend`):
        "Allow on your TV" is a prompt, "Allow phone to be found remotely" a setting."""
        found: list[str] = []
        # An optional extra ("Optionally toggle on Gesture hint…") doesn't decide
        # which screen the group is about — unless it's the only thing there.
        core = [s for s in steps if not s.lower().startswith(("optionally", "(optional)"))] or steps
        for s in core:
            for m in SETTINGS_PATH.finditer(s):
                # "Settings > Display > Screen timeout and choose a longer time":
                # the label ends where the sentence carries on.
                parts = [re.split(r"\s+(?:and|then|to|or|if|when)\s+", p.strip())[0] for p in m.group(1).split(">")]
                found += [p for p in parts if p]
            for m in list(TARGET.finditer(s)) + list(SWITCH_NEXT.finditer(s)):
                label = re.sub(r"\s+again$", "", m.group(1).strip(" '\""), flags=re.I)
                if extend:
                    label = extend(label, [s])
                low = label.lower()
                buttonish = low in BUTTONS or low.split()[0] in ("allow", "unpair", "forget")
                if buttonish and known is not None and Catalog._norm(label) in known:
                    buttonish = False
                if low not in ("settings", "it", "the") and not buttonish:
                    found.append(label)
        seen, out = set(), []
        for t in reversed(found):
            if t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
        return out

    @staticmethod
    def mentions_settings(steps: list[str]) -> bool:
        blob = " ".join(steps).lower()
        return "settings" in blob or bool(ON.search(blob) or OFF.search(blob))

    # ------------------------------------------------------------------ matching
    @staticmethod
    def _norm(text: str) -> str:
        t = text.lower().replace("wi-fi", "wifi").replace("e-mail", "email")
        return " " + re.sub(r"[^a-z0-9]+", " ", t).strip() + " "

    def match(self, action_name: str, steps: list[str]) -> Match | None:
        """Link a step group to a catalogue entry, or None (precision over recall).

        Decided by the *most specific* label the steps end on ("…tap Storage,
        tap Clear cache" is about Clear cache). Rules by label length:
          1 word  → the phrase must appear in the entry's on-screen message
          2 words → both words must appear in the entry
          3+      → at least two thirds must appear
        Entries whose message contains the whole label phrase are preferred.
        With no usable label, rare action-name words (≥ 2, all present) decide.
        """
        if not self.mentions_settings(steps):
            return None
        # Extend first: "Touch" alone is generic, "Touch and hold to edit" is a setting.
        labels = [lab for lab in (self._extend(t, steps) for t in self.targets(steps, self.by_label, self._extend))
                  if any(t not in GENERIC for t in tokens(lab))
                  # "Screen mode" is a real setting even though both words are generic;
                  # "More options" / "Settings" are UI chrome that exists on every OS.
                  or (self._norm(lab) in self.by_label and any(t not in CHROME for t in tokens(lab)))]
        primary = labels[0] if labels else None
        name_toks = [t for t in tokens(action_name) if t not in GENERIC and self.bm25.idf.get(t, 0) >= 2.5]
        if primary is None and len(name_toks) < 2:
            return self._rare_name_match(name_toks)

        polarity = self.polarity(steps)
        # An entry whose on-screen label *is* the step's label beats any partial
        # match: "Bluetooth" → "View Bluetooth", not "View Bluetooth scanning".
        if primary and self._norm(primary) in self.by_label:
            cands = [self.entries[i] for i in self.by_label[self._norm(primary)]]
            # A step with no on/off only opens the page: prefer the entry that opens
            # it over Enable/Disable, which would flip the setting as a side effect.
            toggles = lambda e: e.message.startswith(("Enable", "Disable"))
            # Messages are often shared ("View Notification Settings" names 21 pages);
            # the description names the actual page, so an exact description label wins.
            page = lambda e: self._norm(primary) == self.desc_label(e)
            rank = lambda e: (self.fits(e, polarity), polarity != "View" or not toggles(e), page(e),
                              polarity == "Disable" or not e.message.startswith("Disable"))
            e = max(cands, key=rank)
            return Match(e, 1.0, [t for t in tokens(primary) if t in e.toks])

        basis = [t for t in tokens(primary) if t not in GENERIC] if primary else name_toks
        phrase = self._norm(primary) if primary else None
        query = basis * 4 + name_toks * 2 + tokens(" ".join(steps))
        best, best_key = None, None
        for i, score in self.bm25.top(query, k=20):
            if score <= 0:
                break
            e = self.entries[i]
            in_msg = bool(phrase) and phrase in self._norm(e.message)
            cov = sum(t in e.toks for t in basis) / len(basis)
            if primary and len(basis) == 1:
                ok = in_msg
            elif primary and len(basis) == 2:
                ok = cov == 1.0
            else:
                ok = cov >= 0.67 if primary else cov == 1.0
            # Reject a *different* setting that merely lives on the same page:
            # "Navigation bar" ≠ "Show input method button on navigation bar".
            extra = [t for t in tokens(e.message) if t not in GENERIC and t not in basis]
            if ok and primary and len(extra) >= 2:
                ok = False
            if not ok:
                continue
            # Steps that use/customise a feature need it on: prefer Enable over Disable.
            not_off = polarity == "Disable" or not e.message.startswith("Disable")
            key = (in_msg, cov, self.fits(e, polarity), not_off, score)
            if best_key is None or key > best_key:
                best, best_key = Match(e, score, [t for t in basis if t in e.toks]), key
        # If the steps' own label *is* the rare word ("Font size") and nothing in
        # the catalogue is that label, a dummy link beats a guess from the name.
        own = set(tokens(primary)) if primary else set()
        return best or self._rare_name_match([t for t in name_toks if t not in own])
