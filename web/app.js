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
