import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
from sgte.cache import Cache
from sgte.catalog import DUMMY, get_catalog
from sgte.engine import description, troubleshoot
from sgte.grounding import grounding_rate
from sgte.parse import parse_siis
from sgte.rules import format_errors, url_leaks, words
from sgte.variations import variations

DATA = Path(__file__).resolve().parent.parent / "data"
KIT = json.loads((DATA / "student_kit" / "siis_responses.json").read_text())["responses"]
