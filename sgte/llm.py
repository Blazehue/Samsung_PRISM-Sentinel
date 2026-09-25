"""Optional Gemini layer — language understanding where it helps, never where
correctness is non-negotiable.

Stages (each can be switched off with GEMINI_STAGES):
  understand  — names the topic of an article the symptom lexicon doesn't know,
                and canonicalises a query for the no-article semantic lookup
  rerank      — closed-set deeplink tie-break: picks one of the catalogue
                candidates the rules shortlisted, or "none" (never writes a URI)
  describe    — "It will …" descriptions in plain benefit language
  variations  — 8–10 paraphrases across registers
Steps are never touched: they stay verbatim from the article.

Guardrails: every answer is JSON, validated by the caller's rules; each call
has a time limit and walks a model fallback chain on 404/429/5xx; anything
invalid or late returns None and the deterministic path is used. Results are
memoised by (stage, model, input) in data/llm_cache.json, a persistent cache
(guide Phase 3), so repeats never call Gemini and the committed kit plans are
reproducible with or without a key. The key is read from GEMINI_API_KEY, sent
in a header and never logged.
"""
