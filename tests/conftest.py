"""Tests never call the network: the Gemini key is removed before anything is
imported, so the engine runs on its rules plus the committed Gemini memo
(data/llm_cache.json). Gemini behaviour itself is tested with a stubbed call."""
import os

os.environ.pop("GEMINI_API_KEY", None)
