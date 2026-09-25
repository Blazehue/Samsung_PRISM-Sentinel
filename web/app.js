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
