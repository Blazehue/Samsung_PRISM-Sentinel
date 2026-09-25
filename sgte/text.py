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
