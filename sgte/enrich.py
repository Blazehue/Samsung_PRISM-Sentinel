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
