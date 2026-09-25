"""8–10 diverse paraphrases of a user complaint (block A5).

Deterministic: the device, the main symptom and the situation are extracted
from the query and recombined across the registers the Theme 2 guide lists —
formal, casual, keyword-only, frustrated and typo-inclusive — plus question
and support-ticket phrasings. With GEMINI_API_KEY set, an LLM rewrite is
tried first and falls back to this on any failure.
"""
from __future__ import annotations

import re

from .enrich import enrich
from .text import jaccard, tokens

# symptom → (noun phrases, clauses)
PHRASES = {
    "Blank Screen": (["black screen", "blank display"], ["the screen went black", "the display stays blank"]),
    "Screen Flicker": (["flickering screen", "flashing display"], ["the screen keeps flickering", "the display flashes on and off"]),
    "Cracked Screen": (["cracked screen", "shattered display"], ["the screen is cracked", "the display glass is broken"]),
    "Screen Rotation": (["screen rotation problem", "stuck orientation"], ["the screen won't rotate", "auto rotate stopped working"]),
    "Touchscreen Response": (["unresponsive touchscreen", "laggy touch input"], ["the touchscreen isn't responding", "touch input lags behind"]),
    "Screen Mirroring": (["screen mirroring failure", "Smart View casting problem"], ["I can't mirror my screen", "casting to the TV fails"]),
    "Multi Window": (["split screen problem", "floating window issue"], ["Multi window misbehaves", "a floating app window keeps appearing"]),
    "Data Transfer": (["Smart Switch transfer failure", "stuck data transfer"], ["Smart Switch won't transfer", "I can't move my data"]),
    "Email Connection": (["email connection error", "mail sync problem"], ["email won't load", "the mail app can't reach the server"]),
    "Fingerprint Unlock": (["fingerprint unlock failure", "fingerprint sensor problem"], ["my fingerprint isn't recognised", "fingerprint unlock fails"]),
    "Battery Drain": (["battery drain problem", "charging problem"], ["the battery drains fast", "the phone won't charge properly"]),
    "Notification Delivery": (["missing notification problem", "delayed notifications"], ["notifications don't show up", "alerts arrive late"]),
    "Bluetooth Connection": (["Bluetooth connection problem", "earbud pairing issue"], ["Bluetooth keeps disconnecting", "my earbuds won't stay paired"]),
    "Overheating Battery": (["overheating battery", "swollen battery"], ["the phone gets very hot", "the back of the phone is bulging"]),
    "Font Size": (["small font size", "hard-to-read text"], ["the text is too small", "I can't read the text easily"]),
    "Liquid Damage": (["water-damaged phone", "liquid exposure"], ["the phone got wet", "water got into the device"]),
    "SIM Card Detection": (["SIM detection error", "missing SIM card"], ["the SIM card isn't detected", "the phone says no SIM"]),
    "Random Restarts": (["restart loop", "random reboot problem"], ["the phone keeps restarting", "it reboots on its own"]),
    "Swipe Navigation": (["swipe navigation problem", "gesture navigation glitch"], ["swipes go the wrong way", "the swipe gestures register in the wrong direction"]),
    "Slow Performance": (["slow phone", "laggy performance"], ["the phone got slow", "everything lags and freezes"]),
    "App Crashes": (["app crash", "force-closing app"], ["an app keeps stopping", "the app crashes on launch"]),
    "Network Connection": (["Wi-Fi connection problem", "network dropout"], ["Wi-Fi keeps dropping", "there is no internet connection"]),
    "Display Distortion": (["distorted display", "lines on the screen"], ["the display looks distorted", "lines appear across the screen"]),
}


def _typos(text: str) -> str:
    """Deterministic, human-looking typos in a few longer words (typo-inclusive register)."""
    words, out, n = text.split(), [], 0
    for w in words:
        core = re.sub(r"[^A-Za-z]", "", w)
        if n < 3 and len(core) >= 5 and core.lower() not in {"samsung", "galaxy"}:
            k = len(w) // 2
            w = w[:k] + w[k + 1:] if n % 2 == 0 else w[:k - 1] + w[k] + w[k - 1] + w[k + 1:]   # drop / swap
            n += 1
        out.append(w)
    return " ".join(out)


def _a(noun: str) -> str:
    return ("an " if noun[:1].lower() in "aeiou" else "a ") + noun


def _situation(q: str) -> str | None:
    m = re.search(r"\b(when|whenever|while|after|if)\b ([^,.;]{6,70})", q, re.I)
    return f"{m.group(1).lower()} {m.group(2).strip()}" if m else None
