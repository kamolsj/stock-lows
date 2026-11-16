// Phone UI check: serves site/ with fixture (or real) data, emulates iPhone 13 + Pixel 7,
// asserts layout/behaviour, and saves screenshots to site-screens/.
// Usage: node tools/ui_check.mjs [--real DIR]   (DIR = scanner --out dir; default: fixtures)
import { createRequire } from "node:module";
import { readFileSync, mkdirSync, existsSync } from "node:fs";
import { join, dirname, extname } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium, devices } = require("playwright");
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SITE = join(ROOT, "site");
const OUT = join(ROOT, "site-screens");
const realIdx = process.argv.indexOf("--real");
const REAL = realIdx > 0 ? process.argv[realIdx + 1] : null;
mkdirSync(OUT, { recursive: true });

const now = Date.now();
const iso = (ms) => new Date(ms).toISOString();
function row(sym, ex, price, low, extra = {}) {
  const spark = Array.from({ length: 40 }, (_, i) => +(price * (1.4 - i * 0.01) + Math.sin(i / 3) * 2).toFixed(2));
  return { symbol: sym, name: `${sym} Holdings Corporation Incorporated`, exchange: ex, currency: ex === "TSX" ? "CAD" : "USD",
    price, day_low: low, period_low: Math.min(low, price), period_low_date: "2026-11-16",
    pct_from_low: price / Math.min(low, price) - 1, pct_off_high: -0.38, market_cap: 4.2e10, sector: "Industrials",
    spark: [...spark, price], pe: 14.2, fwd_pe: 12.1, f_score: 7, f_tests: 9, z_score: 3.4, z_zone: "safe",
    rev_growth: 0.04, eps_growth: -0.08, debt_to_equity: 0.6, fcf: 2.1e9, fcf_yield: 0.05, div_yield: 0.031,
    quality: "Strong", sector_check: { stock_pct: -0.3, sector_median_pct: -0.18, verdict: "sector" }, ...extra };
}
const FIX = {
  "status.json": { as_of: iso(now), last_success: iso(now), markets: { XNYS: true, XTSE: true }, ok: true, message: "" },
  "lows-1Y.json": { period: "1Y", as_of: iso(now), new_low: [
      row("ACME", "NYSE", 41.2, 40.8), row("RY.TO", "TSX", 288.4, 286.1, { quality: "Mixed", f_score: 5, z_score: null, z_zone: null, sector: "Financial Services" }),
      row("ZZZ", "NASDAQ", 3.1, 3.0, { quality: "Weak", pe: -2, f_score: 2, z_zone: "distress", z_score: 1.1, sector_check: { stock_pct: -0.6, sector_median_pct: 0.04, verdict: "stock" } })],
    near_low: [row("BBB", "NYSE", 101.5, 99.0), row("CCC.TO", "TSX", 12.3, 12.0, { quality: null, pe: null, f_score: null }),
      row("DDD", "NASDAQ", 55.0, 53.0), row("EEE", "NYSE American", 9.9, 9.6)] },
  "lows-5Y.json": { period: "5Y", as_of: iso(now), new_low: [row("ACME", "NYSE", 41.2, 40.8)], near_low: [] },
  "lows-10Y.json": { period: "10Y", as_of: iso(now), new_low: [], near_low: [] },
  "lows-20Y.json": { period: "20Y", as_of: iso(now), new_low: [], near_low: [] },
  "detail/ACME.json": (() => {
    const daily = [], weekly = [];
    for (let i = 400; i > 0; i--) { const t = Math.floor((now - i * 86400e3) / 1000); daily.push([t, 41 + i * 0.04 + Math.sin(i / 9) * 3, 40.9 + i * 0.04]); }
    for (let i = 1040; i > 0; i--) { const t = Math.floor((now - i * 7 * 86400e3) / 1000); weekly.push([t, 50 + Math.sin(i / 40) * 15, 48 + Math.sin(i / 40) * 15]); }
    return { symbol: "ACME", name: "ACME", currency: "USD", series: { daily, weekly }, lows: {} };
  })(),
};

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".png": "image/png", ".webmanifest": "application/manifest+json" };
let failures = 0;
const check = (ok, msg) => { console.log(`${ok ? "PASS" : "FAIL"} ${msg}`); if (!ok) failures++; };

async function routeSite(page, statusOverride) {
  await page.route("http://site.local/**", async (route) => {
    let path = new URL(route.request().url()).pathname.replace(/^\//, "") || "index.html";
    if (path.startsWith("data/")) {
      const key = path.slice(5);
      if (key === "status.json" && statusOverride) return route.fulfill({ json: statusOverride });
      if (REAL) {
        const f = join(REAL, key);
        return existsSync(f) ? route.fulfill({ path: f, contentType: "application/json" }) : route.fulfill({ status: 404 });
      }
      return FIX[key] ? route.fulfill({ json: FIX[key] }) : route.fulfill({ status: 404 });
    }
    const f = join(SITE, path);
    if (!existsSync(f)) return route.fulfill({ status: 404 });
    return route.fulfill({ body: readFileSync(f), contentType: TYPES[extname(f)] || "application/octet-stream" });
  });
}

const browser = await chromium.launch();
for (const [label, dev] of [["iphone13", devices["iPhone 13"]], ["pixel7", devices["Pixel 7"]]]) {
  for (const scheme of ["light", "dark"]) {
    const ctx = await browser.newContext({ ...dev, colorScheme: scheme });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await routeSite(page);
    await page.goto("http://site.local/index.html");
    await page.waitForSelector(".card");
    await page.waitForTimeout(300);
    const tag = `${label}-${scheme}`;
    const overflow = await page.evaluate((w) => Math.max(document.documentElement.scrollWidth, window.innerWidth) - w, dev.viewport.width);
    if (overflow > 0) console.log(await page.evaluate((w) => [...document.querySelectorAll("body *")].filter((el) => {
      const r = el.getBoundingClientRect(); return r.right > w + 1 && r.width > 0 && !el.closest(".filters"); }).slice(0, 8)
      .map((el) => `${el.tagName}.${el.className} R${Math.round(el.getBoundingClientRect().right)}`), dev.viewport.width));
    check(overflow <= 0, `${tag}: no horizontal overflow (${overflow}px)`);
    await page.screenshot({ path: join(OUT, `${tag}-list.png`), fullPage: true });

    if (!REAL) {
      const c1 = await page.textContent("#c-new");
      await page.click('.seg button[data-period="5Y"]');
      const c5 = await page.textContent("#c-new");
      check(c1 !== c5 && c5.includes("1"), `${tag}: period switch changes counts (${c1} -> ${c5})`);
      await page.click('.seg button[data-period="1Y"]');
      await page.click("#f-f7");
      const cf = await page.textContent("#c-new");
      check(cf.includes("of"), `${tag}: F-Score filter narrows list (${cf})`);
      await page.click("#f-f7");
    }
    if (!REAL) {   // a card without a detail file falls back to the sparkline, still labelled
      await page.locator('.card[aria-label="RY.TO details"]').click();
      await page.waitForTimeout(400);
      check((await page.textContent("#s-chart-note")).toLowerCase().includes("low"), `${tag}: fallback chart keeps low label`);
      await page.click("#s-close");
    }
    await page.locator(REAL ? ".card" : '.card[aria-label="ACME details"]').first().click();
    await page.waitForSelector("#s-chart canvas", { timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(500);
    check(await page.locator("#s-chart canvas").count() > 0, `${tag}: detail chart renders`);
    check((await page.textContent("#s-chart-note")).toLowerCase().includes("low"), `${tag}: low line labelled`);
    const sheetOverflow = await page.evaluate((w) => Math.round(document.getElementById("s-close").getBoundingClientRect().right - w), dev.viewport.width);
    check(sheetOverflow <= 0, `${tag}: detail sheet fits the screen, close button visible (${sheetOverflow}px)`);
    await page.screenshot({ path: join(OUT, `${tag}-detail.png`) });
    check(errors.length === 0, `${tag}: no JS errors ${errors.join(" | ")}`);
    await ctx.close();
  }
}

// stale banner
{
  const ctx = await browser.newContext({ ...devices["iPhone 13"] });
  const page = await ctx.newPage();
  await routeSite(page, { as_of: iso(now), last_success: iso(now - 2 * 3600e3), markets: { XNYS: true, XTSE: false }, ok: false, message: "x" });
  await page.goto("http://site.local/index.html");
  await page.waitForSelector("#banner:not([hidden])");
  check((await page.textContent("#banner")).includes("stale"), "stale banner shown when last scan > 60 min old");
  await page.screenshot({ path: join(OUT, "iphone13-stale.png") });
  await ctx.close();
}
await browser.close();
console.log(failures ? `${failures} FAILED` : "ALL PASSED");
process.exit(failures ? 1 : 0);
