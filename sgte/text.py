"""Text utilities: tokenisation, light stemming, BM25 and a hashed bag-of-words
vector for cheap semantic similarity. Pure Python — fast cold starts, no model
downloads."""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

_WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

STOP = set("""
a an the and or but if then so to of in on at by for with from into onto over under about as is are was
were be been being it its this that these those there here your you my me i we our us they them their he
she his her can could will would should may might must do does did done have has had not no yes than too
very just also only then when while where which who whom what how why all any each both some such more most
other own same again once further up down out off above below between through during before after until
please samsung galaxy device phone tablet mobile smartphone
""".split())

_SYNONYMS = {
    "display": "screen", "monitor": "screen", "lcd": "screen",
    "blank": "black", "dark": "black", "off": "black",
    "flickering": "flicker", "flickers": "flicker", "flashing": "flicker", "flashes": "flicker", "flash": "flicker",
    "wifi": "wi-fi", "wlan": "wi-fi",
    "responding": "respond", "responsive": "respond", "unresponsive": "respond",
    "restart": "reboot", "restarting": "reboot", "reboot": "reboot",
    "apps": "app", "application": "app", "applications": "app",
    "cracked": "crack", "cracks": "crack", "broken": "crack",
    "rotate": "rotation", "rotating": "rotation", "rotates": "rotation", "auto-rotate": "rotation",
    "touchscreen": "touch", "tap": "touch",
}


def stem(w: str) -> str:
    w = _SYNONYMS.get(w, w)
    for suf in ("ing", "edly", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf) and not w.endswith("ss"):
            w = w[: -len(suf)]
            break
    return _SYNONYMS.get(w, w)


def tokens(text: str, keep_stop: bool = False) -> list[str]:
    out = []
    for w in _WORD.findall((text or "").lower()):
        if not keep_stop and w in STOP:
            continue
        out.append(stem(w))
    return out


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class BM25:
    """Okapi BM25 over a list of documents (each a token list)."""

    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.7):
        self.docs, self.k1, self.b = docs, k1, b
        self.N = len(docs)
        self.avgdl = sum(len(d) for d in docs) / max(1, self.N)
        df = Counter(t for d in docs for t in set(d))
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}
        self.tf = [Counter(d) for d in docs]

    def score(self, query: list[str], i: int) -> float:
        tf, dl, s = self.tf[i], len(self.docs[i]), 0.0
        for t in set(query):
            f = tf.get(t)
            if f:
                s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s

    def top(self, query: list[str], k: int = 5) -> list[tuple[int, float]]:
        scored = [(i, self.score(query, i)) for i in range(self.N)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]
