/* SGTE simulator — talks to the live engine API.
   API base: same origin by default; override with ?api=https://host. */
(() => {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const params = new URLSearchParams(location.search);
  const API = (params.get("api") || (location.protocol === "file:" ? "http://localhost:8000" : "")).replace(/\/$/, "");
  const API_LABEL = API || location.origin;

  async function call(path, body) {
    const t0 = performance.now();
    const res = await fetch(API + path, body === undefined ? {} : {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    });
    const rtt = performance.now() - t0;
    if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
    return { data: await res.json(), rtt, cache: res.headers.get("x-cache"), server: parseFloat(res.headers.get("x-latency-ms")) };
  }

  const fmtMs = (ms) => (ms == null || isNaN(ms) ? "—" : ms < 10 ? ms.toFixed(2) + " ms" : ms < 1000 ? ms.toFixed(0) + " ms" : (ms / 1000).toFixed(2) + " s");
  const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);
  const p95 = (xs) => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.floor(0.95 * s.length))] : null; };

  /* ───────────────────────── nav ───────────────────────── */
  const menuBtn = $("#menuBtn"), menu = $("#menu");
  const setMenu = (open) => { menu.hidden = !open; menuBtn.setAttribute("aria-expanded", String(open)); };
  menuBtn.addEventListener("click", (e) => { e.stopPropagation(); setMenu(menu.hidden); });
  menu.addEventListener("click", (e) => { if (e.target.closest("a")) setMenu(false); });
  document.addEventListener("click", (e) => { if (!menu.hidden && !e.target.closest("#nav")) setMenu(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setMenu(false); });

  $$(".base").forEach((el) => (el.textContent = API_LABEL));

  async function ping() {
    const st = $("#apiState");
    try {
      const { data, rtt } = await call("/health");
      const up = data && data.status === "ok";
      st.className = "api-state " + (up ? "up" : "down");
      st.querySelector("span").textContent = up ? `online · ${fmtMs(rtt)}` : "degraded";
      $("#menuApi").textContent = $("#footApi").textContent = `API · ${API_LABEL} · ${up ? "online" : "degraded"}`;
      return up;
    } catch {
      st.className = "api-state down";
      st.querySelector("span").textContent = "offline";
      $("#menuApi").textContent = $("#footApi").textContent = `API · ${API_LABEL} · offline`;
      return false;
    }
  }

  /* ───────────────────────── hero wave ───────────────────────── */
  function startWave() {
    const canvas = $("#wave"), hero = $(".hero"), foot = $(".hero-foot");
    const ctx = canvas.getContext("2d");
    // Small canvas + canvas-level blur: cheap soft edge. (A CSS blur on a
    // full-screen canvas repaints every frame and janks.) Without ctx.filter
    // (Safari), render smaller still and let upscaling soften it.
    const CAN_BLUR = "filter" in ctx;
    const SCALE = CAN_BLUR ? 0.25 : 0.1;
    let w = 0, h = 0, base = 0, amp = 0, running = true, raf = 0;

    const resize = () => {
      w = canvas.width = Math.ceil(hero.clientWidth * SCALE);
      h = canvas.height = Math.ceil(hero.clientHeight * SCALE);
      // Keep the crest above the hero copy so white text always sits on the dark band.
      const footTop = foot.offsetTop * SCALE;
      amp = Math.min(h, w * 0.75);            // a tall, narrow hero would turn the swell into a spike
      base = Math.min(h * 0.62, footTop - amp * 0.2);
    };
    const draw = (t) => {
      ctx.clearRect(0, 0, w, h);
      if (CAN_BLUR) ctx.filter = `blur(${Math.max(2, Math.round(w / 120))}px)`;
      const grad = ctx.createLinearGradient(0, base - h * 0.22, 0, h);
      grad.addColorStop(0, "#050505");
      grad.addColorStop(0.45, "#141414");
      grad.addColorStop(1, "#6b6b6b");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.moveTo(0, h);
      for (let x = 0; x <= w + 2; x += 1) {
        const u = x / w;
        const y = base
          + amp * 0.12 * Math.sin(u * Math.PI * 2 * 0.95 + t * 0.00016)
          + amp * 0.05 * Math.sin(u * Math.PI * 2 * 2.2 - t * 0.00023 + 1.4)
          + amp * 0.02 * Math.sin(u * Math.PI * 2 * 4.1 + t * 0.0004);
        ctx.lineTo(x, y);
      }
      ctx.lineTo(w, h);
      ctx.closePath();
      ctx.fill();
      // A soft lighter core inside the band, like the reference's grey interior.
      const core = ctx.createRadialGradient(w * 0.3, h * 1.05, 0, w * 0.3, h * 1.05, h * 0.55);
      core.addColorStop(0, "rgba(140,140,140,.55)");
      core.addColorStop(1, "rgba(140,140,140,0)");
      ctx.fillStyle = core;
      ctx.fillRect(0, 0, w, h);
      if (CAN_BLUR) ctx.filter = "none";
    };
    let lastT = 0;
    const loop = (t) => {
      if (t - lastT > 33) { draw(t); lastT = t; }          // ~30 fps is plenty for a slow swell
      if (running && !REDUCED) raf = requestAnimationFrame(loop);
    };
    resize();
    addEventListener("resize", () => { resize(); draw(performance.now()); });
    new IntersectionObserver(([e]) => {
      running = e.isIntersecting;
      cancelAnimationFrame(raf);
      if (running) raf = requestAnimationFrame(loop);
    }).observe(hero);
    draw(0);
  }

  /* ───────────────────────── reveals & counters ───────────────────────── */
  function splitWords(root) {
    let i = 0;
    const walk = (node) => {
      [...node.childNodes].forEach((n) => {
        if (n.nodeType === 3) {
          const frag = document.createDocumentFragment();
          n.textContent.split(/(\s+)/).forEach((part) => {
            if (!part) return;
            if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); return; }
            const s = document.createElement("span");
            s.className = "w"; s.style.setProperty("--i", i++); s.textContent = part;
            frag.appendChild(s);
          });
          n.replaceWith(frag);
        } else if (n.nodeType === 1 && n.tagName !== "BR") walk(n);
      });
    };
    walk(root);
  }

  function setRoll(el, value) {
    const str = String(value);
    el.dataset.value = str;
    el.innerHTML = "";
    el.setAttribute("aria-label", str);
    [...str].forEach((ch) => {
      if (/\d/.test(ch)) {
        const col = document.createElement("span");
        col.className = "col"; col.setAttribute("aria-hidden", "true");
        col.innerHTML = Array.from({ length: 10 }, (_, d) => `<span>${d}</span>`).join("");
        col.dataset.d = ch;
        el.appendChild(col);
      } else {
        const f = document.createElement("span");
        f.className = "fixed"; f.textContent = ch; f.setAttribute("aria-hidden", "true");
        el.appendChild(f);
      }
    });
    if (el.classList.contains("rolled")) requestAnimationFrame(() => rollIn(el));
  }
  const rollIn = (el) => { el.classList.add("rolled"); $$(".col", el).forEach((c) => (c.style.transform = `translateY(-${c.dataset.d}em)`)); };

  function initReveals() {
    $$("[data-words]").forEach(splitWords);
    $$(".roll").forEach((el) => setRoll(el, el.dataset.value));
    if (REDUCED || !("IntersectionObserver" in window)) {
      $$("[data-words], .reveal").forEach((el) => el.classList.add("in"));
      $$(".roll").forEach(rollIn);
      return;
    }
    const io = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (!e.isIntersecting) return;
      e.target.classList.add("in");
      $$(".roll", e.target).forEach(rollIn);
      io.unobserve(e.target);
    }), { threshold: 0.15, rootMargin: "0px 0px -8% 0px" });
    $$("[data-words], .reveal").forEach((el) => io.observe(el));
    // Stagger siblings in a grid so cards arrive one after another.
    $$(".tile-grid, .stats, .api-grid").forEach((g) => [...g.children].forEach((c, i) => (c.style.transitionDelay = `${i * 80}ms`)));
  }

  /* ───────────────────────── format rules (mirror of sgte/rules.py) ───────────────────────── */
  const URL_RE = /(https?:\/\/\S+|www\.\S+|\S+\.(?:com|html?|net|org|in|co)\b\S*|!\[[^\]]*\]\([^)]*\)|<a\s[^>]*>|<\/a>)/gi;
  const GOAL_RE = /^Follow these steps to perform this .+ (Troubleshooting|Configuration)\.?$/;
  const words = (s) => String(s || "").trim().split(/\s+/).filter(Boolean);
  const isObj = (o) => o && typeof o === "object" && !Array.isArray(o);

  function schemaOk(r) {
    if (!isObj(r) || !Array.isArray(r.contexts)) return false;
    return r.contexts.every((g) => isObj(g) && typeof g.goal === "string" && typeof g.title === "string" && typeof g.score === "number"
      && Array.isArray(g.actions) && g.actions.every((a) => isObj(a) && typeof a.actionName === "string" && typeof a.description === "string"
      && (a.category == null || ["auto", "manual", "critical"].includes(a.category)) && Array.isArray(a.stepGroups)
      && a.stepGroups.every((sg) => isObj(sg) && Array.isArray(sg.steps) && sg.steps.every((s) => typeof s === "string")
        && (sg.actionableDeeplink == null || (typeof sg.actionableDeeplink.deeplink === "string" && typeof sg.actionableDeeplink.description === "string"))
        && (sg.validationDeeplink == null || (typeof sg.validationDeeplink.deeplink === "string" && typeof sg.validationDeeplink.key === "string")))));
  }
  function urlLeaks(r) {
    return (JSON.stringify(r).match(URL_RE) || []).filter((u) => !u.startsWith("bixby://"));
  }
  function checks(r) {
    const ctx = (r && r.contexts) || [];
    const acts = ctx.flatMap((g) => g.actions || []);
    const groups = acts.flatMap((a) => a.stepGroups || []);
    const links = groups.flatMap((sg) => [sg.actionableDeeplink, sg.validationDeeplink]).filter(Boolean);
    return [
      ["schema", schemaOk(r)],
      ["goal", ctx.length > 0 && ctx.every((g) => GOAL_RE.test(g.goal))],
      ["title 2–3w", ctx.every((g) => { const n = words(g.title).length; return n >= 2 && n <= 3; })],
      ["desc 5–7w", acts.length > 0 && acts.every((a) => a.description.startsWith("It will") && words(a.description).length >= 5 && words(a.description).length <= 7)],
      ["score 0–1", ctx.every((g) => g.score >= 0 && g.score <= 1)],
      ["steps", groups.length > 0 && groups.every((sg) => sg.steps.length && sg.steps.every((s) => s.trim()))],
      ["auto→link", acts.every((a) => a.category !== "auto" || a.stepGroups.every((sg) => sg.actionableDeeplink))],
      ["bixby://", links.every((l) => l.deeplink.startsWith("bixby://"))],
      ["no URLs", urlLeaks(r).length === 0],
    ];
  }
  const canon = (s) => String(s).toLowerCase().replace(/[’]/g, "'").replace(/[“”]/g, '"').replace(/[^a-z0-9]+/g, " ").trim();
  function grounding(r, siis) {
    const src = canon(`${siis.title || ""}\n${siis.content || ""}`.replace(/<[^>]+>/g, " "));
    const steps = ((r && r.contexts) || []).flatMap((g) => g.actions.flatMap((a) => a.stepGroups.flatMap((sg) => sg.steps)));
    return [steps.filter((s) => src.includes(canon(s))).length, steps.length];
  }

  /* ───────────────────────── cases ───────────────────────── */
  const state = { cases: [], paraphrases: {}, source: "kit", current: null, last: null, paraIdx: 0, vars: [] };
  const qIn = $("#qIn"), tIn = $("#tIn"), cIn = $("#cIn");

  async function loadCases() {
    try {
      const { data } = await call("/v1/cases");
      state.cases = data.cases || [];
      state.paraphrases = data.paraphrases || {};
      $("#nKit").textContent = state.cases.filter((c) => c.source === "kit").length;
      $("#nUnseen").textContent = state.cases.filter((c) => c.source === "unseen").length;
      renderChips();
      const first = state.cases.find((c) => c.source === "kit");
      if (first) selectCase(first);          // open on a real run, not an empty panel
    } catch (err) {
      $("#caseChips").innerHTML = `<span class="muted small">Couldn't reach ${esc(API_LABEL)}. Start the API with <code>uvicorn app:app</code>, or add <code>?api=https://host</code> to this page's URL.</span>`;
    }
  }

  function renderChips() {
    const box = $("#caseChips");
    if (state.source === "custom") {
      box.innerHTML = `<span class="muted small">Write any complaint and paste any SIIS-style article. Markdown headers, lists and plain prose all work.</span>`;
      return;
    }
    const list = state.cases.filter((c) => c.source === state.source);
    box.innerHTML = list.map((c) => `<button class="chip${state.current && state.current.id === c.id ? " on" : ""}" data-id="${esc(c.id)}" title="${esc(c.query)}"><b>${esc(c.id.replace("unseen_", "u"))}</b><span>${esc(c.query.replace(/^\s*\d+\.\s*/, ""))}</span></button>`).join("");
  }

  function selectCase(c, run = true) {
    state.current = c;
    state.paraIdx = 0;
    qIn.value = c.query;
    tIn.value = c.siis_response.title || "";
    cIn.value = c.siis_response.content || "";
    $("#caseLabel").textContent = `${c.id} · ${c.source}`;
    renderChips();
    if (run) runTroubleshoot();
  }

  $(".seg").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-src]");
    if (!b) return;
    $$(".seg button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-selected", String(x === b)); });
    state.source = b.dataset.src;
    if (state.source === "custom") {
      state.current = null;
      $("#caseLabel").textContent = "custom";
      qIn.focus();
    }
    renderChips();
  });
  $("#caseChips").addEventListener("click", (e) => {
    const b = e.target.closest(".chip");
    if (!b) return;
    const c = state.cases.find((x) => x.id === b.dataset.id);
    if (c) selectCase(c);
  });

  /* ───────────────────────── run ───────────────────────── */
  const runBtn = $("#runBtn"), repeatBtn = $("#repeatBtn"), paraBtn = $("#paraBtn");
  const readInput = () => ({ query: qIn.value.trim(), siis_response: { title: tIn.value, content: cIn.value } });

  $("#runForm").addEventListener("submit", (e) => { e.preventDefault(); runTroubleshoot(); });
  repeatBtn.addEventListener("click", () => runTroubleshoot({ keepVars: true }));
  paraBtn.addEventListener("click", () => {
    const own = state.current && state.paraphrases[state.current.id];
    const pool = own && own.length ? own : state.vars;
    if (!pool.length) return;
    qIn.value = pool[state.paraIdx++ % pool.length];
    runTroubleshoot({ keepVars: true });
  });

  async function runTroubleshoot({ keepVars = false } = {}) {
    const body = readInput();
    // No article is allowed: the engine then looks the query up among pre-warmed scenarios (guide §5).
    if (!body.query && !body.siis_response.content.trim() && !body.siis_response.title.trim()) { qIn.focus(); return; }
    runBtn.disabled = true;
    runBtn.firstChild.textContent = "Running… ";
    try {
      const [ts, insp, vars] = await Promise.all([
        call("/v1/troubleshoot", body),
        call("/v1/inspect", body).catch(() => null),
        keepVars ? Promise.resolve(null) : call("/v1/variations", { query: body.query || body.siis_response.title }).catch(() => null),
      ]);
      state.last = { body, ...ts, inspect: insp && insp.data };
      if (vars) state.vars = vars.data.query_variations || [];
      renderStrip(ts, body);
      renderPlan(ts.data);
      renderPipe(insp && insp.data, ts.data);
      renderVars();
      renderJson(ts.data);
      updateBand(ts, insp && insp.data);
      phone.load(ts.data);
      repeatBtn.disabled = paraBtn.disabled = false;
    } catch (err) {
      $("#planEmpty").hidden = false;
      $("#plan").hidden = true;
      $("#planEmpty").innerHTML = `<p class="h-empty">The API didn't answer.</p><p class="muted">${esc(err.message)}. Is the server running at ${esc(API_LABEL)}?</p>`;
    } finally {
      runBtn.disabled = false;
      runBtn.firstChild.textContent = "Run troubleshoot ";
    }
  }

  function renderStrip(ts, body) {
    const cache = ts.cache || "—";
    const [g, n] = grounding(ts.data, body.siis_response);
    const ch = checks(ts.data), ok = ch.filter(([, v]) => v).length;
    const set = (id, v, cls = "") => { const el = $(id); el.textContent = v; el.className = cls; el.parentElement.classList.remove("flash"); void el.offsetWidth; el.parentElement.classList.add("flash"); };
    set("#sCache", cache === "miss" ? "miss" : cache, cache === "miss" ? "miss" : cache === "—" ? "" : "hit");
    set("#sServer", fmtMs(ts.server));
    set("#sRtt", fmtMs(ts.rtt));
    set("#sGround", n ? `${g}/${n}` : "—");
    set("#sFormat", `${ok}/${ch.length}`);
  }

  function linkChip(dl, kind) {
    if (!dl) return "";
    if (kind === "val") {
      const cond = dl.condition ? ` ${dl.condition === "equal" ? "=" : dl.condition} ${esc(dl.value)}` : "";
      return `<span class="dl"><span aria-hidden="true">✓</span><b>${esc(dl.key)}${cond}</b><code>${esc(dl.deeplink)}</code></span>`;
    }
    const dummy = dl.deeplink === "bixby://dummy_positive";
    return `<span class="dl${dummy ? " dummy" : ""}"><span aria-hidden="true">↗</span><b>${esc(dl.message || dl.description)}</b><code>${esc(dl.deeplink)}</code></span>`;
  }

  function renderPlan(r) {
    const empty = $("#planEmpty"), plan = $("#plan");
    if (!r.contexts || !r.contexts.length) {
      empty.hidden = false; plan.hidden = true;
      const why = r.fallback === "no_siis_context"
        ? "No article was sent and the query didn't clearly match any pre-warmed scenario."
        : "The article contains no instructions to follow, so the engine returned an empty plan instead of inventing steps.";
      empty.innerHTML = `<p class="h-empty">No plan · <code>${esc(r.fallback || "no_match")}</code></p><p class="muted">${why}</p>`;
      return;
    }
    empty.hidden = true; plan.hidden = false;
    const g = r.contexts[0];
    const kind = /Configuration\.?$/.test(g.goal) ? "Configuration" : "Troubleshooting";
    const meta = r.meta ? `<span class="badge">${esc(r.meta.model)} · $${Number(r.meta.cost_usd).toFixed(2)}</span>` : "";
    const ch = checks(r);
    plan.innerHTML = `
      <div class="goal">
        <div class="goal-top"><span class="badge dark">${esc(g.title)}</span><span class="badge">${kind}</span><span class="badge">${g.actions.length} actions</span>${meta}</div>
        <p class="goal-text">${esc(g.goal)}</p>
        <div class="score"><span>score</span><div class="bar"><i style="width:${Math.round(g.score * 100)}%"></i></div><span>${g.score.toFixed(2)}</span></div>
      </div>
      <ol class="actions">${g.actions.map((a, ai) => `
        <li class="action${ai === 0 ? " open" : ""}" style="--i:${ai}">
          <button class="a-head" type="button" aria-expanded="${ai === 0}">
            <span class="a-num">${String(ai + 1).padStart(2, "0")}</span>
            <span><span class="a-name">${esc(a.actionName)}</span><span class="a-desc">${esc(a.description)}</span></span>
            <span class="a-meta"><span class="cat ${esc(a.category || "manual")}">${esc(a.category || "manual")}</span><span class="chev" aria-hidden="true">▾</span></span>
          </button>
          <div class="a-body"><div><div class="groups">${a.stepGroups.map((sg) => `
            <div class="group">
              <ol class="steps">${sg.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
              ${sg.actionableDeeplink || sg.validationDeeplink ? `<div class="links">${linkChip(sg.actionableDeeplink, "act")}${linkChip(sg.validationDeeplink, "val")}</div>` : ""}
            </div>`).join("")}
            <button class="sim-btn" type="button" data-sim="${ai}">Simulate on device →</button>
          </div></div></div>
        </li>`).join("")}
      </ol>
      <div class="checks-row">${ch.map(([k, v]) => `<span class="check${v ? "" : " bad"}">${v ? "✓" : "✕"} ${esc(k)}</span>`).join("")}</div>`;
  }

  $("#plan").addEventListener("click", (e) => {
    const sim = e.target.closest("[data-sim]");
    if (sim) { phone.jumpToAction(+sim.dataset.sim); $("#phone").scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "center" }); return; }
    const head = e.target.closest(".a-head");
    if (!head) return;
    const li = head.parentElement;
    li.classList.toggle("open");
    head.setAttribute("aria-expanded", String(li.classList.contains("open")));
  });

  function renderPipe(insp, r) {
    const box = $("#pipe");
    if (!insp) { box.innerHTML = `<p class="muted">Pipeline details are unavailable from this API.</p>`; return; }
    const e = insp.enriched;
    const links = insp.sections.flatMap((s) => s.groups.map((g) => g.link)).filter(Boolean);
    box.innerHTML = `
      <div><h4>01 · Enrichment</h4><div class="kv">
        <span><i>device</i>${esc(e.device || "not named")}</span>
        <span><i>symptoms</i>${esc(e.symptoms.join(", ") || "none detected")}</span>
        <span><i>intent</i>${e.is_issue ? "fix an issue" : "how-to"}</span>
      </div><div class="kv" style="margin-top:6px">${e.keywords.map((k) => `<span>${esc(k)}</span>`).join("")}</div></div>
      <div><h4>02 · Sections parsed from “${esc(insp.siis_title)}”</h4><div class="pipe">${insp.sections.map((s) => `
        <div class="sec-box"><p class="sec-title">${esc(s.title)}</p>
          <p class="sec-meta"><span><b>${s.groups.reduce((n, g) => n + g.steps.length, 0)}</b> steps</span><span><b>${s.groups.length}</b> group${s.groups.length > 1 ? "s" : ""}</span>
          ${s.groups.map((g) => g.targets.length ? `<span>labels: ${g.targets.slice(0, 4).map(esc).join(" · ")}</span>` : "").join("")}
          ${s.groups.map((g) => g.link ? `<span>→ <b>${esc(g.link.id === "bixby://dummy_positive" ? "dummy · " + (g.link.screen || "") : g.link.message)}</b>${g.link.matched ? ` <span class="muted">(matched: ${g.link.matched.map(esc).join(", ")})</span>` : ""}</span>` : "").join("")}</p>
        </div>`).join("") || `<p class="muted">No actionable sections.</p>`}</div></div>
      <div><h4>03 · Deeplinks</h4><div class="kv"><span><i>catalogue</i>${links.filter((l) => l.id !== "bixby://dummy_positive").length}</span><span><i>dummy</i>${links.filter((l) => l.id === "bixby://dummy_positive").length}</span><span><i>unlinked groups</i>${insp.sections.reduce((n, s) => n + s.groups.filter((g) => !g.link).length, 0)}</span></div></div>`;
  }

  function renderVars() {
    const box = $("#vars");
    if (!state.vars.length) { box.innerHTML = `<li><span class="muted">No variations yet.</span></li>`; return; }
    box.innerHTML = state.vars.map((v, i) => `<li><span>${esc(v)}</span><button type="button" data-v="${i}">Run</button></li>`).join("");
  }
  $("#vars").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-v]");
    if (!b) return;
    qIn.value = state.vars[+b.dataset.v];
    selectTab("plan");
    runTroubleshoot({ keepVars: true });
  });

  function renderJson(r) {
    const s = esc(JSON.stringify(r, null, 2));
    $("#json").innerHTML = s.replace(/(&quot;(?:[^&]|&(?!quot;))*?&quot;)(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?)/g, (m, str, colon, lit, num) =>
      str ? `<span class="${colon ? "k" : "s"}">${str}</span>${colon || ""}` : lit ? `<span class="b">${lit}</span>` : `<span class="n">${num}</span>`);
  }
  $("#copyJson").addEventListener("click", async (e) => {
    if (!state.last) return;
    try { await navigator.clipboard.writeText(JSON.stringify(state.last.data, null, 2)); e.target.textContent = "Copied"; }
    catch { e.target.textContent = "Copy failed"; }
    setTimeout(() => (e.target.textContent = "Copy"), 1400);
  });

  function selectTab(name) {
    $$(".tabs button").forEach((b) => { const on = b.dataset.tab === name; b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on)); });
    $$(".tab-body").forEach((t) => (t.hidden = t.id !== "tab-" + name));
  }
  $(".tabs").addEventListener("click", (e) => { const b = e.target.closest("button[data-tab]"); if (b) selectTab(b.dataset.tab); });

  function updateBand(ts, insp) {
    const r = ts.data, g = r.contexts && r.contexts[0];
    const put = (id, html) => ($(`#${id} .rc-v`).innerHTML = html);
    if (insp) {
      const e = insp.enriched;
      put("pc-enrich", `${esc(e.device || "Device not named")}<small>${esc(e.symptoms.slice(0, 2).join(" · ") || "no symptom detected")} · ${e.is_issue ? "fix" : "how-to"}</small>`);
      const steps = insp.sections.reduce((n, s) => n + s.groups.reduce((m, gg) => m + gg.steps.length, 0), 0);
      put("pc-parse", `${insp.sections.length} sections · ${steps} steps<small>${grounding(r, state.last.body.siis_response).join("/")} grounded in the article</small>`);
    }
    const groups = g ? g.actions.flatMap((a) => a.stepGroups) : [];
    const acts = groups.map((sg) => sg.actionableDeeplink).filter(Boolean);
    const dummy = acts.filter((l) => l.deeplink === "bixby://dummy_positive").length;
    put("pc-link", g ? `${acts.length - dummy} catalogue · ${dummy} dummy<small>${esc((acts[0] && acts[0].message) || "no Settings screens in this article")}</small>` : "—");
    const ch = checks(r);
    put("pc-compose", g ? `${ch.filter(([, v]) => v).length}/${ch.length} rules pass<small>${esc(g.goal)}</small>` : "No contexts");
    put("pc-cache", `${esc(ts.cache || "—")} · ${fmtMs(ts.server)}<small>round trip ${fmtMs(ts.rtt)} from this browser</small>`);
  }

  /* ───────────────────────── phone ───────────────────────── */
  const phone = (() => {
    const app = $("#app"), settings = $("#settings"), sheet = $("#sheet");
    let plan = null, seq = [], i = 0, confirmed = new Set(), verified = new Set();

    const screenName = (dl) => {
      let m = (dl.message || dl.description || "Settings").replace(/\s+in device Settings$/i, "");
      m = m.replace(/^(View|Enable|Disable|Open|Check|Diagnose|Set|Turn on|Turn off)\s+/i, "");
      return m || "Settings";
    };
    const polarity = (dl) => (/^Enable\b/i.test(dl.message || "") ? "on" : /^Disable\b/i.test(dl.message || "") ? "off" : "view");

    function load(r) {
      plan = r.contexts && r.contexts[0];
      seq = [];
      confirmed = new Set(); verified = new Set();
      if (plan) plan.actions.forEach((a, ai) => a.stepGroups.forEach((g, gi) => g.steps.forEach((s, si) =>
        seq.push({ ai, gi, si, a, g, text: s, n: g.steps.length }))));
      i = 0;
      closeSettings(); closeSheet();
      render();
    }
    function jumpToAction(ai) {
      const k = seq.findIndex((x) => x.ai === ai);
      if (k >= 0) { i = k; closeSettings(); render(); }
    }
    function render() {
      if (!plan) { app.innerHTML = `<div class="app-idle"><div class="app-mark">SGTE</div><p>No plan for this article — nothing to walk through.</p></div>`; return; }
      if (i >= seq.length) {
        const opened = new Set(seq.filter((x) => x.g.actionableDeeplink).map((x) => `${x.ai}.${x.gi}`)).size;
        app.innerHTML = `<div class="done"><div class="tick">✓</div><p class="t">Fix complete</p><p class="muted small">${seq.length} steps · ${opened} shortcut${opened === 1 ? "" : "s"} · ${verified.size} verified</p>
          <div class="nav-row" style="margin-top:18px"><button class="back" data-go="restart">Restart</button><button class="next" data-go="back">Review</button></div></div>`;
        return;
      }
      const x = seq[i], cat = x.a.category || "manual";
      if (cat === "critical" && !confirmed.has(x.ai)) openSheet(x);
      const key = `${x.ai}.${x.gi}`;
      const link = x.g.actionableDeeplink, val = x.g.validationDeeplink;
      app.innerHTML = `
        <div class="app-bar"><span>Guided fix</span><span class="step-count">${i + 1} / ${seq.length}</span></div>
        <p class="app-title">${esc(plan.title)}</p>
        <div class="prog"><i style="width:${((i + 1) / seq.length) * 100}%"></i></div>
        <div class="step-card">
          <div class="sc-top"><span class="sc-action">${String(x.ai + 1).padStart(2, "0")} · ${esc(x.a.actionName)}</span><span class="cat ${esc(cat)}">${esc(cat)}</span></div>
          <span class="step-count">step ${x.si + 1} of ${x.n}</span>
          <p class="step-text">${esc(x.text)}</p>
          ${verified.has(key) && val ? `<div class="verified">✓ Verified · ${esc(val.key)}${val.condition ? ` ${val.condition === "equal" ? "=" : esc(val.condition)} ${esc(val.value)}` : ""}</div>` : ""}
          ${link ? `<button class="open-link" data-go="open"><span>${link.deeplink === "bixby://dummy_positive" ? "Shortcut · placeholder link" : "Shortcut · deeplink"}</span><b>${esc(link.message || link.description)} ↗</b></button>` : ""}
        </div>
        <div class="nav-row"><button class="back" data-go="prev" ${i === 0 ? "disabled" : ""}>Back</button><button class="next" data-go="next">${i === seq.length - 1 ? "Finish" : "Next step"}</button></div>`;
    }
    function openSettings(x) {
      const dl = x.g.actionableDeeplink, val = x.g.validationDeeplink, pol = polarity(dl);
      const name = screenName(dl);
      settings.innerHTML = `
        <button class="set-back" data-go="close">‹ Guided fix</button>
        <p class="set-title">${esc(name)}</p>
        <div class="set-group">
          <div class="set-row"><span>${esc(val ? val.key : name)}<small>${esc(dl.description || "")}</small></span>
            ${pol === "view" ? `<span class="muted">›</span>` : `<span class="toggle${pol === "off" ? " on" : ""}" id="tg"></span>`}</div>
        </div>
        <p class="set-uri">${esc(dl.deeplink)}${dl.originalType ? " · " + esc(dl.originalType) : ""}</p>
        ${val ? `<button class="verify-btn" data-go="verify">Verify · ${esc(val.key)}</button>` : `<button class="verify-btn" data-go="close">Done</button>`}`;
      settings.classList.add("show");
      settings.setAttribute("aria-hidden", "false");
      if (pol !== "view") setTimeout(() => { const t = $("#tg"); if (t) t.classList.toggle("on", pol === "on"); }, REDUCED ? 0 : 650);
    }
    function closeSettings() { settings.classList.remove("show"); settings.setAttribute("aria-hidden", "true"); }
    function openSheet(x) {
      sheet.innerHTML = `<div class="panel"><div class="warn">!</div><h5>Before you continue</h5>
        <p>“${esc(x.a.actionName)}” is marked critical. It can erase data or involves device safety. Back up first and continue only if you're sure.</p>
        <div class="row2"><button class="skip" data-go="skip">Skip action</button><button class="go" data-go="confirm">Continue</button></div></div>`;
      sheet.classList.add("show");
      sheet.setAttribute("aria-hidden", "false");
    }
    function closeSheet() { sheet.classList.remove("show"); sheet.setAttribute("aria-hidden", "true"); }

    $("#phone").addEventListener("click", (e) => {
      const b = e.target.closest("[data-go]");
      if (!b) return;
      const x = seq[i];
      switch (b.dataset.go) {
        case "next": i = Math.min(seq.length, i + 1); render(); break;
        case "prev": i = Math.max(0, i - 1); render(); break;
        case "restart": i = 0; confirmed = new Set(); verified = new Set(); render(); break;
        case "back": i = Math.max(0, seq.length - 1); render(); break;
        case "open": openSettings(x); break;
        case "close": closeSettings(); break;
        case "verify": verified.add(`${x.ai}.${x.gi}`); closeSettings(); render(); break;
        case "confirm": confirmed.add(x.ai); closeSheet(); break;
        case "skip": {
          closeSheet();
          const nxt = seq.findIndex((y, k) => k > i && y.ai !== x.ai);
          i = nxt < 0 ? seq.length : nxt;
          render();
          break;
        }
      }
    });
    const tick = () => { const d = new Date(); $("#clock").textContent = `${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`; };
    tick(); setInterval(tick, 30000);
    return { load, jumpToAction };
  })();
