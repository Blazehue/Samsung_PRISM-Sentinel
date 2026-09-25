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
