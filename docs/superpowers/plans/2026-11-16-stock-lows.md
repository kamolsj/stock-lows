# Stock Lows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A phone-friendly static web page, refreshed about every 15 minutes by GitHub Actions, listing NYSE / NASDAQ / NYSE American / TSX stocks that hit (or are within 5% of) their 1Y / 5Y / 10Y / 20Y low today, with charts and quality KPIs.

**Architecture:** A Python package `stocklows` (all network access isolated in `yahoo.py`) builds the universe weekly, keeps split-adjusted daily history in a Parquet store (Actions cache), precomputes per-period stats nightly, and runs a light intraday scan that writes JSON. A vanilla-JS static site on the `gh-pages` branch reads that JSON. The `gh-pages` branch is kept to a single commit (amend + force-push) so the repo never bloats.

**Tech Stack:** Python 3.12, pandas, pyarrow, yfinance, exchange_calendars, requests, pytest; vanilla HTML/CSS/JS + TradingView Lightweight Charts 4.1.3 (unpkg, pinned); Playwright for UI checks; GitHub Actions + GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-11-16-stock-lows-design.md`

## Global Constraints

- Exchanges: NYSE, NASDAQ, NYSE American, TSX. Common shares only (no ETFs, funds, warrants, units, preferreds, rights).
- Liquidity floor (own currency): price ≥ 2, market cap ≥ 300,000,000, 20-day average dollar volume ≥ 1,000,000.
- Periods: `1Y`=365, `5Y`=1826, `10Y`=3652, `20Y`=7305 calendar days back from today.
- "Hit new low today": `day_low <= prior_low`, where `prior_low` = min daily Low over `[today - period_days, yesterday]`.
- "Near low": `price <= period_low * 1.05`, where `period_low = min(prior_low, day_low)`; excludes rows already in "new low".
- Stocks whose first history date is after `today - period_days` are excluded from that period.
- Prices: split-adjusted, NOT dividend-adjusted (yfinance `auto_adjust=False`, use Low/Close, never "Adj Close").
- F-Score 0–9, strong ≥ 7. Altman Z zones: > 3 safe, 1.8–3 grey, < 1.8 distress; `None` for sector "Financial Services".
- Scan when NYSE (`XNYS`) or TSX (`XTSE`) is open; each stock uses its own exchange's calendar.
- Stale warning when last successful scan is > 60 minutes old during market hours.
- Native currency, labelled (USD / CAD).
- Never publish a failed scan; keep last good data and its timestamp.
- Page footer text: "For research only — not investment advice. A few listed stocks may not be offered on Wealthsimple; confirm in the app."

## Review Focus

1. A stock split inside the stored history: appended unadjusted rows would create a fake "new low". Expect: a split triggers a full re-download for that ticker (test in Task 4).
2. A run before the open, on a holiday, or one that gets yesterday's bar: expect no flags and no publish of new lists (test in Task 7).
3. Yahoo returns a partial batch (missing tickers, NaN lows): expect those tickers skipped, and no publish if > 20% of the universe is missing (test in Task 7).
4. A recently listed stock with less history than the period: expect it excluded from that period (test in Task 3).
5. Class-share symbols (`BRK.B`, `RCI.B`, `BBD/B`): expect correct Yahoo symbols (`BRK-B`, `RCI-B.TO`, `BBD-B.TO`) (test in Task 5).

---

## File Structure

```
stock-lows/
  pyproject.toml
  stocklows/
    __init__.py
    config.py        # constants from Global Constraints
    yahoo.py         # ONLY module doing network I/O (yfinance + HTTP)
    marketcal.py     # open/closed checks per exchange
    lows.py          # pure: period stats + low detection
    history.py       # Parquet store, append, split refresh
    universe.py      # parse listings, symbol mapping, filters
    fundamentals.py  # pure: F-Score, Z-Score, KPIs, quality badge
    sectors.py       # pure: "sector down too?" check
    publish.py       # build JSON, sanity checks, write site data
    cli.py           # `python -m stocklows <probe|universe|nightly|intraday|fundamentals>`
  tests/ (pytest, fixtures in tests/fixtures/)
  site/ index.html, app.js, style.css, manifest.webmanifest, icon-192.png, icon-512.png
  tools/ui_check.mjs   # Playwright phone screenshots + smoke assertions
  .github/workflows/ intraday.yml, nightly.yml, weekly.yml, keepalive.yml
  README.md            # includes click-by-click GitHub setup
```

Data contract (written under `site/data/`, served by Pages):
- `status.json`: `{"as_of": ISO8601, "last_success": ISO8601, "markets": {"XNYS": bool, "XTSE": bool}, "ok": bool, "message": str}`
- `lows-{1Y|5Y|10Y|20Y}.json`: `{"period": str, "as_of": str, "new_low": [Row], "near_low": [Row]}`
- `detail/{yahoo_symbol}.json`: `{"symbol", "name", "currency", "series": {"daily": [[epoch_s, close, low]...] (last 400 trading days), "weekly": [[epoch_s, close, low]...] (20Y)}, "lows": {period: {"low", "date"}}, "kpis": Kpis}`
- `Row`: `symbol, name, exchange, currency, price, day_low, period_low, period_low_date, pct_from_low, pct_off_high, market_cap, sector, spark (≤ 60 closes), pe, fwd_pe, f_score, z_score, z_zone, rev_growth, eps_growth, debt_to_equity, fcf, fcf_yield, div_yield, quality, sector_check`

---

### Task 1: Scaffold + live data probe

**Files:**
- Create: `pyproject.toml`, `stocklows/__init__.py`, `stocklows/config.py`, `stocklows/yahoo.py`, `stocklows/cli.py`, `tests/test_config.py`

**Interfaces:**
- Produces (`yahoo.py`):
  - `download_daily(symbols: list[str], start: date | None, period: str | None = None) -> dict[str, pd.DataFrame]` with columns `Open High Low Close Volume Splits`, DatetimeIndex (tz-naive dates). Batches of 200, 3 retries with exponential backoff (2, 4, 8 s); missing symbols are omitted from the result.
  - `fetch_info(symbol: str) -> dict` (raw `Ticker.info`).
  - `fetch_statements(symbol: str) -> dict[str, pd.DataFrame]` with keys `income`, `balance`, `cashflow` (annual).
  - `fetch_us_listings() -> list[dict]` (NASDAQ screener `https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true` per exchange `nyse|nasdaq|amex`: fields symbol, name, marketCap, sector, exchange).
  - `fetch_tsx_listings() -> list[dict]` (TMX company directory JSON; fields symbol, name).
- Produces (`config.py`): `PERIODS: dict[str, int]`, `NEAR_PCT = 0.05`, `MIN_PRICE = 2`, `MIN_MCAP = 300_000_000`, `MIN_DOLLAR_VOL = 1_000_000`, `STALE_MINUTES = 60`, `MAX_MISSING_FRAC = 0.20`.

- [ ] **Step 1:** Test `tests/test_config.py::test_periods` asserting `PERIODS == {"1Y": 365, "5Y": 1826, "10Y": 3652, "20Y": 7305}` and `NEAR_PCT == 0.05`. Run → FAIL. Implement config. Run → PASS.
- [ ] **Step 2:** Implement `yahoo.py` as above. Implement `python -m stocklows probe`, which prints for each source: OK/FAIL, row counts, and for `AAPL`, `RY.TO`, `BRK-B` the last 3 daily bars and `info["marketCap"]`. Exit code 1 if any source fails.
- [ ] **Step 3:** Run the probe live (sandbox network must allow Yahoo/NASDAQ/TMX; request the environment change if blocked). Expected: all OK. If TMX or the NASDAQ screener endpoint differs from the above, fix the parser here and note the real endpoint in `yahoo.py`. Record the probe output in the task report.
- [ ] **Step 4:** Commit `feat: scaffold and live data probe`.

### Task 2: Market calendar

**Files:** Create `stocklows/marketcal.py`, `tests/test_marketcal.py`

**Interfaces:**
- Produces: `is_open(exchange: str, at: datetime) -> bool` (`"XNYS"`/`"XTSE"`, `at` tz-aware); `session_date(exchange: str, at: datetime) -> date | None` (today's session date if a session has started by `at`, else None); `exchange_for_symbol(symbol: str) -> str` (`.TO` → `XTSE`, else `XNYS`).

- [ ] **Step 1:** Tests: `is_open("XNYS", 2026-11-16 10:00 ET) is True`; `is_open("XNYS", 2026-11-26 10:00 ET) is False` (Thanksgiving); `is_open("XTSE", 2026-11-26 10:00 ET) is True`; `is_open("XNYS", 2026-11-16 09:00 ET) is False`; `session_date("XNYS", 2026-11-16 09:00 ET) is None`; `exchange_for_symbol("RY.TO") == "XTSE"`. Run → FAIL.
- [ ] **Step 2:** Implement with `exchange_calendars`. Run → PASS. Commit `feat: market calendar`.

### Task 3: Period stats and low detection (core accuracy)

**Files:** Create `stocklows/lows.py`, `tests/test_lows.py`

**Interfaces:**
- Produces:
  - `PeriodStat` dataclass: `prior_low: float, prior_low_date: date, period_high: float, start_close: float, spark: list[float]`.
  - `period_stats(hist: pd.DataFrame, today: date) -> dict[str, PeriodStat]`: uses rows with index < today; omits a period when `hist.index.min() > today - timedelta(days)`; `spark` = Close resampled to ≤ 60 evenly spaced points.
  - `classify(stat: PeriodStat, day_low: float, price: float) -> Literal["new_low", "near_low"] | None`, per Global Constraints.
  - `pct_from_low(price, period_low) -> float` (e.g. 0.031 for 3.1%), `pct_off_high(price, period_high) -> float`.

- [ ] **Step 1:** Tests on a synthetic DataFrame (lows from 2016-01-04 to 2026-11-13, min 1Y low 50.0 on 2026-03-02):
  - `test_new_low_when_day_low_touches_prior_low`: `classify(stat_1Y, day_low=50.0, price=53.0) == "new_low"` (bounced, still counts).
  - `test_not_new_low_above`: `classify(stat_1Y, 50.01, 50.5) == "near_low"`.
  - `test_near_low_boundary`: price `52.5` → `"near_low"`; `52.51` → `None`.
  - `test_today_excluded_from_prior`: a row dated `today` with Low 10 does not change `prior_low`.
  - `test_short_history_excluded`: a ticker starting 2023-01-03 has `"1Y"` but not `"5Y"`, `"10Y"`, `"20Y"`.
  - `test_spark_length_le_60`.
  Run → FAIL.
- [ ] **Step 2:** Implement. Run → PASS. Commit `feat: period stats and low detection`.

### Task 4: History store

**Files:** Create `stocklows/history.py`, `tests/test_history.py`

**Interfaces:**
- Consumes: `yahoo.download_daily`.
- Produces: `HistoryStore(path: Path)` with `load() -> dict[str, pd.DataFrame]`, `update(symbols: list[str], today: date, downloader=yahoo.download_daily) -> dict[str, pd.DataFrame]`, `save()`. Storage: one Parquet file `history.parquet` (long format: symbol, date, Low, Close, Volume) at `path`.
- Update rule: symbols not stored → download `period="max"`; others → download from the last stored date; **if the new rows contain a nonzero `Splits`, re-download that symbol with `period="max"` and replace it.**

- [ ] **Step 1:** Tests with a fake downloader: `test_new_symbol_full_download`; `test_append_only_new_dates` (no duplicate dates); `test_split_triggers_full_redownload` (the fake returns `Splits=2.0` on the new day; assert that the second call used `period="max"` and the old rows were replaced by the adjusted ones); `test_roundtrip_save_load`. Run → FAIL.
- [ ] **Step 2:** Implement. Run → PASS. Commit `feat: parquet history store with split refresh`.

### Task 5: Universe

**Files:** Create `stocklows/universe.py`, `tests/test_universe.py`, `tests/fixtures/us_listings.json`, `tests/fixtures/tsx_listings.json` (small samples captured from the Task 1 probe)

**Interfaces:**
- Consumes: `yahoo.fetch_us_listings`, `yahoo.fetch_tsx_listings`, `yahoo.fetch_info` (TSX market cap/sector only), history (price + dollar volume).
- Produces: `Stock` dataclass `symbol (Yahoo), name, exchange ("NYSE"|"NASDAQ"|"NYSE American"|"TSX"), currency ("USD"|"CAD"), sector, market_cap`; `to_yahoo(raw_symbol: str, exchange: str) -> str`; `is_common_share(name: str, symbol: str) -> bool`; `build_universe(...) -> list[Stock]`; `apply_liquidity(stocks, hist) -> list[Stock]`; saved as `state/universe.json`.

- [ ] **Step 1:** Tests: `to_yahoo("BRK.B","NYSE")=="BRK-B"`, `to_yahoo("BRK/B","NYSE")=="BRK-B"`, `to_yahoo("RCI.B","TSX")=="RCI-B.TO"`, `to_yahoo("BBD/B","TSX")=="BBD-B.TO"`, `to_yahoo("RY","TSX")=="RY.TO"`; `is_common_share` is False for names containing `ETF`, `Fund`, `Trust Units`, `Warrant`, `Rights`, `Preferred`, `Depositary Shares Representing Preferred`, ` Units`, and for TSX symbols with `.PR.` / `.WT` / `.UN`; True for `"Apple Inc. Common Stock"`. `apply_liquidity` drops price 1.99, mcap 299,999,999, and dollar volume 999,999. Run → FAIL.
- [ ] **Step 2:** Implement. Run → PASS. Commit `feat: universe build and filters`.

### Task 6: Fundamentals, quality badge, sector check

**Files:** Create `stocklows/fundamentals.py`, `stocklows/sectors.py`, `tests/test_fundamentals.py`, `tests/test_sectors.py`

**Interfaces:**
- Produces:
  - `piotroski(stmts: dict[str, pd.DataFrame]) -> int | None` (needs 2 annual years; None if missing). The nine standard tests: ROA > 0; CFO > 0; ΔROA > 0; CFO > net income; Δ(long-term debt/assets) < 0; Δcurrent ratio > 0; shares outstanding not increased; Δgross margin > 0; Δasset turnover > 0.
  - `altman_z(stmts, market_cap: float, sector: str) -> float | None`: `1.2·WC/TA + 1.4·RE/TA + 3.3·EBIT/TA + 0.6·MVE/TL + 1.0·Sales/TA`; None for `"Financial Services"`. `z_zone(z) -> "safe"|"grey"|"distress"|None`.
  - `kpis(info: dict, stmts, sector) -> Kpis` (TypedDict with the Row KPI fields).
  - `quality(k: Kpis) -> "Strong"|"Mixed"|"Weak"|"Unknown"`, with the rule:
    - Unknown if `f_score is None`.
    - Strong if `f_score >= 7` and (`z_zone == "safe"` or sector is `"Financial Services"`) and `pe > 0` and `fcf > 0`.
    - Weak if `f_score <= 3` or `z_zone == "distress"` or (`pe <= 0 or pe is None`) and `fcf < 0`.
    - Otherwise Mixed.
    - `QUALITY_RULE_TEXT` constant: a plain-English version shown in the UI.
  - `sector_check(stock_pct: float, sector_pcts: list[float]) -> {"stock_pct", "sector_median_pct", "verdict": "sector"|"stock"|"unknown"}`: verdict "sector" if the median ≤ −0.10, "stock" otherwise, "unknown" if fewer than 5 peers.
- [ ] **Step 1:** Tests: a hand-worked two-year statement fixture giving F-Score exactly 7 (write the nine pass/fails in a comment); a Z-Score fixture giving `3.25 ± 0.01` → `"safe"`; `z_zone(1.79)=="distress"`, `z_zone(1.8)=="grey"`, `z_zone(3.0)=="grey"`; bank → `altman_z(...) is None`; quality cases for each branch; `sector_check(-0.30, [-0.2]*6)["verdict"]=="sector"`, `sector_check(-0.30, [0.05]*6)["verdict"]=="stock"`, 4 peers → "unknown". Run → FAIL.
- [ ] **Step 2:** Implement. Run → PASS. Commit `feat: fundamentals, quality badge, sector check`.

### Task 7: Publish, sanity checks, CLI pipelines

**Files:** Create `stocklows/publish.py`, extend `stocklows/cli.py`, `tests/test_publish.py`, `tests/test_cli_e2e.py`

**Interfaces:**
- Consumes: everything above.
- Produces CLI commands (each takes `--state DIR` (Actions-cached) and `--out DIR` (site/data)):
  - `universe`: build + save `state/universe.json`.
  - `nightly`: update history; write `state/stats.json` (per symbol per period: PeriodStat + 52w high + start_close) and `out/detail/*.json` for symbols within 15% of any period low.
  - `fundamentals`: compute KPIs for the detail set + any current candidates; cache them in `state/fundamentals.json` with a fetched date; refetch if older than 7 days.
  - `intraday`: download today's bars for the universe, classify, attach KPIs + sector check, and write `lows-*.json` + `status.json`. Missing detail/KPIs are shown as `null` (UI shows "loading").
- `sanity_check(quotes, universe, session_dates) -> list[str]` (errors). Fails if: missing fraction > 0.20; any price ≤ 0; any `new_low` row with `day_low > prior_low`; the quote bar date ≠ the exchange session date. When a stock's bar is from a previous date (pre-open or holiday for that exchange), that stock is silently skipped, not counted as an error.
- On failure: write `status.json` with `ok=false`, the message and the previous `last_success`; leave `lows-*.json` untouched; exit 0 (so the workflow still deploys the status).
- [ ] **Step 1:** Tests: `test_partial_batch_over_20pct_blocks_publish`; `test_holiday_bars_skipped` (TSX open, NYSE closed: only `.TO` rows flagged); `test_preopen_no_flags`; `test_failed_scan_keeps_previous_lists`; `test_row_shape` (all Row keys present); an e2e test running `nightly` + `intraday` on fixture history with fake downloaders, asserting a known ticker in `lows-1Y.json["new_low"]` and another in `near_low`. Run → FAIL.
- [ ] **Step 2:** Implement. Run → PASS. Commit `feat: publish pipeline and sanity checks`.

### Task 8: Mobile site

**Files:** Create `site/index.html`, `site/app.js`, `site/style.css`, `site/manifest.webmanifest`, icons, `site/data/` sample fixture output, `tools/ui_check.mjs`

**Interfaces:**
- Consumes: the data contract above.
- Behavior:
  - Top bar with title "Stock Lows" and "Prices as of 2:45 PM ET · 15-min delayed". A red banner "Data is stale since …" when `!ok` or `last_success` is older than 60 minutes while any market is open. A "Markets closed" chip otherwise.
  - Segmented control 1Y | 5Y | 10Y | 20Y (default 1Y, remembered in localStorage inside try/catch).
  - Filter chips: Exchange (All / US / TSX), Positive P/E, F-Score ≥ 7, Z safe, Min cap (300M / 1B / 10B). Sort select: Closest to low (default) / Quality / Market cap / % off high.
  - Two sections, "Hit new low today (n)" and "Near low · within 5% (n)", with cards: symbol, name, exchange badge, price + currency, % from low, sparkline (canvas), quality badge, P/E, F-Score.
  - Tap a card → bottom sheet: Lightweight Charts line chart for the selected period (daily series for 1Y, weekly for the others), a horizontal price line at the period low labelled with its date, the KPI grid with plain-English hints, the sector check sentence, a "Why this badge?" toggle showing the rule text, and a link "Open in Yahoo Finance".
  - Pull-to-refresh / Refresh button re-fetches JSON with cache-busting `?t=`. Auto re-fetch every 5 minutes while visible.
  - Empty state: "No stocks hit a new {period} low today." Light/dark via `prefers-color-scheme`. Min tap target 44px. No horizontal scroll at 360px width. Footer text from Global Constraints.
- [ ] **Step 1:** Write `tools/ui_check.mjs`. It serves `site/` locally, opens iPhone 13 and Pixel 7 emulations, and asserts: there is no horizontal overflow; the period switch changes the counts; opening a card shows the chart canvas and the low line label; the stale banner appears when `status.json` is stale. It saves screenshots to `site-screens/`. Run → FAIL (no site).
- [ ] **Step 2:** Build the site. Run `node tools/ui_check.mjs` → all assertions PASS. Review the screenshots against common finance-app patterns (Yahoo Finance and Wealthsimple mobile layouts researched on the web) and fix any spacing or legibility issues. Commit `feat: mobile site`.

### Task 9: GitHub Actions, keep-alive, README

**Files:** Create `.github/workflows/intraday.yml`, `nightly.yml`, `weekly.yml`, `keepalive.yml`, `README.md`

- Intraday: cron `*/15 13-21 * * 1-5` (UTC; covers 9:30–16:00 ET in both EST and EDT; the CLI exits early if neither market is open). `concurrency: scan` with cancel-in-progress false. It restores `state/` from `actions/cache` (key `state-${{ github.run_id }}`, restore-keys `state-`), runs `intraday`, then checks out `gh-pages`, copies `site/` + `out/`, does `git commit --amend` and force-pushes, then saves the cache.
- Nightly: `30 22 * * 1-5` → `nightly`, then `fundamentals`. Weekly: `0 10 * * 6` → `universe`, `nightly`, `fundamentals`. The first-ever run is `workflow_dispatch` of weekly.
- Keepalive: monthly; runs `gh workflow enable` for each workflow (`permissions: actions: write`).
- README: what it is, the phone link, and a click-by-click setup (create the repo, push, Settings → Pages → branch `gh-pages`, run "weekly" once, bookmark / Add to Home Screen).
- [ ] **Step 1:** Validate the workflow YAML with `actionlint` (download the pinned binary). Expected: no errors. Commit `ci: scheduled scans and pages deploy`.

### Task 10: Live verification

- [ ] **Step 1:** With the network open to Yahoo, run `universe → nightly → fundamentals → intraday` locally against real data. Record: universe size per exchange (expect US 1,500–3,500 after filters, TSX 200–600), runtime per step, and list counts per period.
- [ ] **Step 2:** Spot-check 10 flagged stocks (at least 3 TSX) against a second public source: the 52-week low on stockanalysis.com / TMX Money / MarketWatch. Expected: our prior low is within 1% of theirs, or the difference is explained (e.g. they include today). Record a table.
- [ ] **Step 3:** Hand-verify the F-Score and Z-Score for 2 stocks against their published statements.
- [ ] **Step 4:** Run `tools/ui_check.mjs` on the real data and review the screenshots.
- [ ] **Step 5:** If GitHub is connected: create the repo in the owner's account, push, enable Pages, dispatch weekly, then confirm intraday publishes and the phone URL loads. Otherwise hand over the README guide.
