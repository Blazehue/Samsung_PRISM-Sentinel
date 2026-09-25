# Smart Guided Troubleshooting Engine (SGTE)

**PRISM Gen AI Hackathon 2026 · Theme 02 — Guided Troubleshooting**

SGTE turns a vague Galaxy device complaint and a Samsung SIIS knowledge article
into a structured, deeplinked troubleshooting plan. The plan has a goal, actions
ordered from least to most disruptive, one interaction per step, and deeplinks
that open the exact Settings screen and verify the fix.

```
POST /v1/troubleshoot
{ "query": "My Galaxy S22 screen turns blank…", "siis_response": { "title": "…", "content": "…" } }
→ ContextDeeplinkResponse (validated against the kit's schema.py) + meta {latency_ms, cache_hit, model, cost_usd}
```

## Architecture

### System view

```mermaid
flowchart LR
    subgraph Clients
        J[Judges' scorer / any REST client]
        W[Simulator site<br/>web/ · plain HTML/CSS/JS]
    end
    subgraph API["FastAPI service · app.py (one container)"]
        R["/v1/troubleshoot"]
        V["/v1/variations"]
        H["/health · /v1/metrics"]
        I["/v1/cases · /v1/inspect"]
    end
    subgraph Engine["sgte/ engine (pure Python)"]
        C[cache.py<br/>exact · paraphrase · semantic]
        E[enrich.py<br/>query understanding]
        P[parse.py<br/>SIIS → sections → steps]
        K[catalog.py<br/>deeplink index + matcher]
        G[engine.py<br/>compose · order · validate]
        VR[variations.py<br/>8–10 paraphrases]
        L[llm.py<br/>Gemini refinement<br/>validated · time-boxed · cached]
    end
    subgraph Data["data/ (read-only)"]
        D1[(deeplinks.json<br/>578 entries)]
        D2[(siis_responses.json<br/>20 kit cases)]
        S[(schema.py<br/>pydantic contract)]
    end
    J --> R & H
    W --> R & V & H & I
    R --> C
    C -- miss --> G
    G --> E & P & K
    K --> D1
    G --> S
    V --> VR -. key set .-> L
    G -. cache miss .-> L
    L --> M[(llm_cache.json<br/>persistent Gemini cache)]
    D2 -- pre-warm at startup --> C
```
