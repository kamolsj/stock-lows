/* Stock Lows — static front end. Reads data/*.json written by the scanner. */
(() => {
  "use strict";

  const PERIODS = ["1Y", "5Y", "10Y", "20Y"];
  const PERIOD_NAME = { "1Y": "1-year", "5Y": "5-year", "10Y": "10-year", "20Y": "20-year" };
  const STALE_MIN = 60;
  const AUTO_REFRESH_MS = 5 * 60 * 1000;
  const QUALITY_ORDER = { Strong: 0, Mixed: 1, Weak: 2, Unknown: 3 };
  const QUALITY_RULE =
    "Strong: F-Score 7 or more, Altman Z above 3 (safe; not used for banks/insurers), positive P/E " +
    "and positive free cash flow. Weak: F-Score 3 or less, or Altman Z below 1.8 (distress), or losing " +
    "money with negative free cash flow. Mixed: everything in between. Unknown: not enough financial data yet.";

  const $ = (s, r = document) => r.querySelector(s);
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
  };

  const state = {
    period: PERIODS.includes(store.get("period", "1Y")) ? store.get("period", "1Y") : "1Y",
    filters: Object.assign({ exchange: "all", pe: false, f7: false, z: false, cap: 0, sort: "low" },
      store.get("filters", {})),
    lists: {}, status: null, loading: false,
  };

  // ---------- formatting
  const fmtPx = (v) => v == null ? "—" : v >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 0 })
    : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtPct = (v, signed = true) => v == null ? "—"
    : `${signed && v > 0 ? "+" : ""}${(v * 100).toFixed(Math.abs(v) < 0.1 ? 1 : 0)}%`;
  const fmtCap = (v) => {
    if (v == null) return "—";
    if (v >= 1e12) return `${(v / 1e12).toFixed(1)}T`;
    if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
    return `${(v / 1e6).toFixed(0)}M`;
  };
  const fmtNum = (v, d = 1) => v == null ? "—" : v.toFixed(d);
  const fmtMoney = (v) => v == null ? "—" : `${v < 0 ? "−" : ""}${fmtCap(Math.abs(v))}`;
  const fmtDate = (iso) => {
    if (!iso) return "—";
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  };
  const fmtTimeET = (iso) => new Date(iso).toLocaleString("en-US", {
    timeZone: "America/New_York", hour: "numeric", minute: "2-digit", weekday: "short",
  });
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- data
  async function getJSON(path) {
    const r = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  }

  async function load() {
    if (state.loading) return;
    state.loading = true;
    $("#refresh").classList.add("spin");
    try {
      const [status, ...lists] = await Promise.all([
        getJSON("data/status.json").catch(() => null),
        ...PERIODS.map((p) => getJSON(`data/lows-${p}.json`).catch(() => null)),
      ]);
      state.status = status;
      PERIODS.forEach((p, i) => { state.lists[p] = lists[i]; });
    } finally {
      state.loading = false;
      $("#refresh").classList.remove("spin");
      render();
    }
  }

  // ---------- filtering / sorting
  function applyFilters(rows) {
    const f = state.filters;
    let out = rows.filter((r) =>
      (f.exchange === "all" || (f.exchange === "tsx" ? r.exchange === "TSX" : r.exchange !== "TSX")) &&
      (!f.pe || (r.pe != null && r.pe > 0)) &&
      (!f.f7 || (r.f_score != null && r.f_score >= 7)) &&
      (!f.z || r.z_zone === "safe") &&
      (!f.cap || (r.market_cap != null && r.market_cap >= f.cap)));
    const by = {
      low: (a, b) => a.pct_from_low - b.pct_from_low,
      quality: (a, b) => (QUALITY_ORDER[a.quality] ?? 4) - (QUALITY_ORDER[b.quality] ?? 4) || (b.f_score ?? -1) - (a.f_score ?? -1) || a.pct_from_low - b.pct_from_low,
      cap: (a, b) => (b.market_cap ?? 0) - (a.market_cap ?? 0),
      high: (a, b) => a.pct_off_high - b.pct_off_high,
    }[f.sort] || ((a, b) => a.pct_from_low - b.pct_from_low);
    return out.slice().sort(by);
  }

  // ---------- rendering
  function renderStatus() {
    const st = state.status;
    const banner = $("#banner");
    const list = state.lists[state.period];
    const asOf = list?.as_of;
    $("#asof").textContent = asOf
      ? `Prices as of ${fmtTimeET(asOf)} ET · 15-min delayed`
      : "No scan has finished yet.";
    banner.hidden = true;
    banner.className = "banner";
    if (!st) {
      banner.hidden = false;
      banner.textContent = "Couldn't load the latest data. Pull to refresh or try again in a minute.";
      return;
    }
    const anyOpen = st.markets && (st.markets.XNYS || st.markets.XTSE);
    const ageMin = st.last_success ? (Date.now() - Date.parse(st.last_success)) / 60000 : Infinity;
    if (!st.ok || (anyOpen && ageMin > STALE_MIN)) {
      banner.hidden = false;
      banner.textContent = st.last_success
        ? `Data is stale since ${fmtTimeET(st.last_success)} ET. The latest update didn't complete; showing the last good scan.`
        : "Data is stale: no successful scan yet.";
    } else if (!anyOpen) {
      banner.hidden = false;
      banner.classList.add("info");
      banner.textContent = "Markets are closed. Showing the most recent trading day.";
    }
  }

  function card(r) {
    const li = document.createElement("li");
    const q = r.quality || "null";
    const sec = r.sector_check?.verdict === "sector" ? "Sector down too"
      : r.sector_check?.verdict === "stock" ? "Stock-specific drop" : null;
    li.innerHTML = `
      <button class="card" type="button" aria-label="${esc(r.symbol)} details">
        <div class="c-row">
          <span><span class="sym">${esc(r.symbol.replace(/\.TO$/, ""))}</span><span class="ex">${esc(r.exchange)}</span></span>
          <span class="px">${fmtPx(r.price)} <span class="ccy">${esc(r.currency)}</span></span>
        </div>
        <div class="c-row">
          <span class="nm">${esc(r.name)}</span>
          <span class="fromlow">${r.pct_from_low <= 0.0005 ? "at low" : `${fmtPct(r.pct_from_low)} above low`}</span>
        </div>
        <canvas class="spark" aria-hidden="true"></canvas>
        <div class="tags">
          <span class="tag q-${esc(q)}">${r.quality ? esc(r.quality) : "Quality loading"}</span>
          <span class="tag">P/E ${r.pe != null && r.pe > 0 ? fmtNum(r.pe) : r.pe != null ? "neg." : "—"}</span>
          <span class="tag">F-Score ${r.f_score ?? "—"}</span>
          ${sec ? `<span class="tag">${sec}</span>` : ""}
        </div>
      </button>`;
    li.querySelector("button").addEventListener("click", () => openSheet(r));
    requestAnimationFrame(() => drawSpark(li.querySelector("canvas"), r.spark, r.period_low));
    return li;
  }

  function drawSpark(cv, pts, low) {
    if (!cv || !pts || pts.length < 2) return;
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth, h = cv.clientHeight;
    cv.width = w * dpr; cv.height = h * dpr;
    const ctx = cv.getContext("2d");
    ctx.scale(dpr, dpr);
    const cs = getComputedStyle(document.documentElement);
    const lo = Math.min(...pts, low ?? Infinity), hi = Math.max(...pts);
    const pad = 3, span = hi - lo || 1;
    const x = (i) => pad + (i / (pts.length - 1)) * (w - pad * 2);
    const y = (v) => pad + (1 - (v - lo) / span) * (h - pad * 2);
    if (low != null) {   // the period low, dashed
      ctx.strokeStyle = cs.getPropertyValue("--low-line").trim();
      ctx.setLineDash([3, 3]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pad, y(low)); ctx.lineTo(w - pad, y(low)); ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.strokeStyle = cs.getPropertyValue("--series").trim();
    ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.lineCap = "round";
    ctx.beginPath();
    pts.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
    ctx.stroke();
    ctx.fillStyle = ctx.strokeStyle;   // end dot = latest price
    ctx.beginPath(); ctx.arc(x(pts.length - 1), y(pts[pts.length - 1]), 3, 0, Math.PI * 2); ctx.fill();
  }

  function renderList(el, countEl, rows, total, emptyText) {
    el.replaceChildren();
    countEl.textContent = rows.length === total ? `(${total})` : `(${rows.length} of ${total})`;
    if (!rows.length) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = total ? "No stocks match these filters." : emptyText;
      el.append(li);
      return;
    }
    const frag = document.createDocumentFragment();
    rows.forEach((r) => frag.append(card(r)));
    el.append(frag);
  }

  function render() {
    document.querySelectorAll(".seg button").forEach((b) =>
      b.setAttribute("aria-selected", String(b.dataset.period === state.period)));
    document.querySelectorAll(".p-name").forEach((s) => { s.textContent = PERIOD_NAME[state.period]; });
    const f = state.filters;
    $("#f-exchange").value = f.exchange; $("#f-cap").value = String(f.cap); $("#f-sort").value = f.sort;
    $("#f-pe").setAttribute("aria-pressed", String(f.pe));
    $("#f-f7").setAttribute("aria-pressed", String(f.f7));
    $("#f-z").setAttribute("aria-pressed", String(f.z));
    renderStatus();
    const data = state.lists[state.period] || { new_low: [], near_low: [] };
    const pn = PERIOD_NAME[state.period];
    renderList($("#l-new"), $("#c-new"), applyFilters(data.new_low), data.new_low.length,
      `No stocks hit a new ${pn} low today.`);
    renderList($("#l-near"), $("#c-near"), applyFilters(data.near_low), data.near_low.length,
      `No stocks are within 5% of their ${pn} low right now.`);
  }

  // ---------- detail sheet
  let chart = null;
  function kpi(label, value, hint) {
    return `<div class="kpi"><div class="k">${label}</div><div class="v">${value}</div>${hint ? `<div class="h">${hint}</div>` : ""}</div>`;
  }

  async function openSheet(r) {
    const sheet = $("#sheet");
    $("#s-title").textContent = r.symbol.replace(/\.TO$/, "");
    $("#s-name").textContent = `${r.name} · ${r.exchange}${r.sector ? " · " + r.sector : ""}`;
    const pn = PERIOD_NAME[state.period];
    const sc = r.sector_check || {};
    const secText = sc.verdict === "sector"
      ? `Its sector is down too (typical ${r.exchange === "TSX" ? "Canadian" : "US"} peer: ${fmtPct(sc.sector_median_pct)} over ${pn}; this stock: ${fmtPct(sc.stock_pct)}). The drop looks more like market or sector timing.`
      : sc.verdict === "stock"
        ? `Its sector is not down much (typical peer: ${fmtPct(sc.sector_median_pct)} over ${pn}; this stock: ${fmtPct(sc.stock_pct)}). The drop looks company-specific — worth checking the news.`
        : "Not enough sector peers to compare.";
    const range = r.pct_off_high != null ? r.price / (1 + r.pct_off_high) : Math.max(r.price, ...(r.spark || [r.price]));
    const posPct = range > r.period_low ? ((r.price - r.period_low) / (range - r.period_low)) * 100 : 0;
    const zText = r.z_zone === "safe" ? "Safe (> 3)" : r.z_zone === "grey" ? "Grey zone (1.8–3)" : r.z_zone === "distress" ? "Distress (< 1.8)" : null;
    $("#s-body").innerHTML = `
      <p class="big-px">${fmtPx(r.price)} <span class="ccy">${esc(r.currency)}</span></p>
      <p class="sub">${pn} low ${fmtPx(r.period_low)} on ${fmtDate(r.period_low_date)} · ${fmtPct(r.pct_from_low)} above it · ${fmtPct(r.pct_off_high)} from the period high</p>
      <div class="chart" id="s-chart" role="img" aria-label="${esc(r.symbol)} price over ${pn}"></div>
      <p class="chart-note" id="s-chart-note"><span class="legend-line"></span>${pn} low</p>
      <div class="range" aria-label="Where the price sits between the period low and high">
        <div class="range-track"><div class="range-dot" style="left:${Math.min(100, Math.max(0, posPct)).toFixed(1)}%"></div></div>
        <div class="range-lbl"><span>Low ${fmtPx(r.period_low)}</span><span>High ${fmtPx(range)}</span></div>
      </div>
      <div class="kpis">
        ${kpi("Quality", `<span class="tag q-${esc(r.quality || "null")}">${esc(r.quality || "Loading")}</span>`)}
        ${kpi("P/E (trailing)", r.pe == null ? "—" : r.pe > 0 ? fmtNum(r.pe) : "Negative", "Price ÷ last year's earnings")}
        ${kpi("Forward P/E", r.fwd_pe == null ? "—" : fmtNum(r.fwd_pe), "Uses analysts' next-year estimate")}
        ${kpi("Piotroski F-Score", r.f_score == null ? "—" : `${r.f_score} / 9`, r.f_tests && r.f_tests < 9 ? `Scaled from ${r.f_tests} available tests` : "7+ = financially strong")}
        ${kpi("Altman Z-Score", r.z_score == null ? "—" : fmtNum(r.z_score, 2), zText || (/financ/i.test(r.sector) ? "Not used for financials" : "Bankruptcy-risk gauge"))}
        ${kpi("Revenue growth", fmtPct(r.rev_growth), "Last fiscal year")}
        ${kpi("EPS growth", fmtPct(r.eps_growth), "Last fiscal year")}
        ${kpi("Debt / equity", r.debt_to_equity == null ? "—" : fmtNum(r.debt_to_equity, 2), "Lower = less leverage")}
        ${kpi("Free cash flow", fmtMoney(r.fcf), r.fcf_yield != null ? `${fmtPct(r.fcf_yield, false)} of market cap` : "")}
        ${kpi("Dividend yield", r.div_yield == null ? "—" : fmtPct(r.div_yield, false))}
        ${kpi("Market cap", fmtCap(r.market_cap), esc(r.currency))}
        ${kpi("Day's low", fmtPx(r.day_low), "Lowest trade today")}
      </div>
      <div class="note">${secText}</div>
      <details><summary>Why this quality badge?</summary><p>${QUALITY_RULE}</p></details>
      <a class="ext" href="https://finance.yahoo.com/quote/${encodeURIComponent(r.symbol)}" target="_blank" rel="noopener">Open in Yahoo Finance ↗</a>`;
    if (!sheet.open) sheet.showModal();
    drawChart(r);
  }

  async function drawChart(r) {
    const el = $("#s-chart");
    if (chart) { chart.remove(); chart = null; }
    $("#s-chart-note").innerHTML = `<span class="legend-line"></span>${PERIOD_NAME[state.period]} low`;
    let detail = null;
    try { detail = await getJSON(`data/detail/${encodeURIComponent(r.symbol)}.json`); } catch { /* no detail yet */ }
    if (!el.isConnected) return;
    const days = { "1Y": 365, "5Y": 1826, "10Y": 3652, "20Y": 7305 }[state.period];
    let pts;
    if (detail) {
      const series = state.period === "1Y" ? detail.series.daily : detail.series.weekly;
      const cutoff = Date.now() / 1000 - days * 86400;
      pts = series.filter((p) => p[0] >= cutoff).map((p) => ({ time: p[0], value: p[1] }));
      const today = Math.floor(Date.now() / 86400000) * 86400;
      if (pts.length && today > pts[pts.length - 1].time) pts.push({ time: today, value: r.price });
    }
    if (!pts || pts.length < 2 || !window.LightweightCharts) {
      el.style.height = "auto";
      el.innerHTML = `<canvas class="spark" style="height:120px"></canvas>`;
      requestAnimationFrame(() => drawSpark(el.querySelector("canvas"), r.spark, r.period_low));
      $("#s-chart-note").innerHTML = `<span class="legend-line"></span>${PERIOD_NAME[state.period]} low · full chart available after tonight's update`;
      return;
    }
    const cs = getComputedStyle(document.documentElement);
    const c = (n) => cs.getPropertyValue(n).trim();
    chart = LightweightCharts.createChart(el, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: c("--muted"), fontSize: 11 },
      grid: { vertLines: { visible: false }, horzLines: { color: c("--border") } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { mode: 0 },
      handleScroll: false, handleScale: false,
    });
    const line = chart.addAreaSeries({
      lineColor: c("--series"), lineWidth: 2,
      topColor: `color-mix(in srgb, ${c("--series")} 22%, transparent)`, bottomColor: "transparent",
      priceLineVisible: false, lastValueVisible: true,
    });
    line.setData(pts);
    line.createPriceLine({ price: r.period_low, color: c("--low-line"), lineWidth: 2, lineStyle: 2,
      axisLabelVisible: true, title: `Low ${fmtDate(r.period_low_date)}` });
    chart.timeScale().fitContent();
  }

  // ---------- wiring
  function saveAndRender() { store.set("filters", state.filters); render(); }
  document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
    state.period = b.dataset.period; store.set("period", state.period); render();
  }));
  $("#f-exchange").addEventListener("change", (e) => { state.filters.exchange = e.target.value; saveAndRender(); });
  $("#f-cap").addEventListener("change", (e) => { state.filters.cap = Number(e.target.value); saveAndRender(); });
  $("#f-sort").addEventListener("change", (e) => { state.filters.sort = e.target.value; saveAndRender(); });
  [["#f-pe", "pe"], ["#f-f7", "f7"], ["#f-z", "z"]].forEach(([id, k]) =>
    $(id).addEventListener("click", () => { state.filters[k] = !state.filters[k]; saveAndRender(); }));
  $("#refresh").addEventListener("click", load);
  $("#s-close").addEventListener("click", () => $("#sheet").close());
  $("#sheet").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
  $("#sheet").addEventListener("close", () => { if (chart) { chart.remove(); chart = null; } });

  // pull-to-refresh (simple): drag down from the very top
  let startY = null;
  window.addEventListener("touchstart", (e) => { startY = window.scrollY <= 0 ? e.touches[0].clientY : null; }, { passive: true });
  window.addEventListener("touchend", (e) => {
    if (startY != null && e.changedTouches[0].clientY - startY > 90) load();
    startY = null;
  }, { passive: true });

  setInterval(() => { if (document.visibilityState === "visible") load(); }, AUTO_REFRESH_MS);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load(); });
  let lastW = window.innerWidth;
  window.addEventListener("resize", () => { if (window.innerWidth !== lastW) { lastW = window.innerWidth; render(); } });

  load();
})();
