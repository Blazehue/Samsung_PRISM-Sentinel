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
