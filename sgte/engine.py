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
