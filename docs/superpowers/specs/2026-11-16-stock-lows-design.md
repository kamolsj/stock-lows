# Stock Lows — Design

Date: 2026-11-16

## Intent

A phone-friendly web page that lists North American stocks (buyable on Wealthsimple) that
**hit their lowest price of a chosen period today**, plus those **near** that low, with charts and
quality signals so the owner can spot good companies that are cheap because of timing or the
market environment, not because the business is broken. It is a research/report tool, not a
stock picker and not advice.

The owner checks it on their phone, during the trading day. They are not technical; it must
"just work" and be obviously trustworthy (clear "last updated" time, numbers that add up).

## Goals

1. Universe: common stocks on **NYSE, NASDAQ, NYSE American, and TSX** (the main Wealthsimple
   venues). Exclude ETFs, funds, warrants, units, preferreds, rights.
2. Period selector like a stock chart: **1Y, 5Y, 10Y, 20Y**. Periods are independent options,
   not nested tabs.
3. Two lists per period:
   - **Hit new low today**: today's intraday low ≤ the lowest daily low over the period
     *before* today. The stock counts even if it has bounced since (this is the analyst
     definition of "made a new 52-week low").
   - **Near low**: current price within **5%** of the period low (5% is the common analyst
     "near 52-week low" cutoff). Excludes stocks already in the first list.
4. Every row shows a small chart (sparkline) of the period. Tapping a row opens a detail
   view with a full price chart for the selected period, the low marked with a line/marker,
   and all KPIs.
5. Quality signals per stock (computed for candidates only):
   - P/E (trailing), forward P/E, with a **"Positive P/E only"** filter
   - **Piotroski F-Score** (0–9; 7+ = strong) — standard second-stage value-trap filter
   - **Altman Z-Score** (>3 safe, 1.8–3 grey, <1.8 distress). Not meaningful for banks /
     insurers: show "n/a (financial)" for those.
   - Revenue growth (YoY), earnings growth (YoY), debt-to-equity, free cash flow (sign +
     yield), dividend yield, market cap, sector
   - **"Sector down too?"** flag: compare the stock's drop over the period with its sector's
     typical drop (median of same-sector stocks in our universe). If the sector is also down a lot
     it's more likely timing/environment; if only this stock fell, it's company-specific.
   - A plain-language **Quality badge** (Strong / Mixed / Weak) combining the above, with the
     rule shown on tap (so it's never a black box).
6. Filters on the page: exchange (All / US / TSX), positive P/E, F-Score ≥ 7, Altman Z safe,
   minimum market cap. Sort by: distance from low, quality, market cap, % off 52-week high.
7. Data refreshes about every 15 minutes during market hours (9:30–16:00 ET, Mon–Fri, market
   holidays skipped). 15-minute delayed data is acceptable. Page shows "Prices as of HH:MM ET"
   and a clear stale warning if the last successful scan is older than ~1 hour during market
   hours. Pull-to-refresh / Refresh button re-loads the latest published data.
8. Prices in native currency (USD for US, CAD for TSX), labelled.

## Non-goals

- Predicting winners, buy/sell signals, alerts, portfolio tracking, logins.
- Tick-by-tick real-time data.
- TSXV, CSE, CBOE Canada, OTC, penny stocks.
- Reading news to explain *why* a stock fell (the sector flag + fundamentals are the proxy).

## Anti-goals (failure even if it "works")

- Numbers that don't add up (e.g., a "new low today" stock whose low isn't actually below the
  prior period low; split-unadjusted history creating fake lows).
- Silently showing stale data as if current.
- A list flooded with penny stocks / illiquid junk.
- Clunky on a phone.

## Constraints

- **Free data only.** Source: Yahoo Finance via the `yfinance` Python library (covers NYSE,
  NASDAQ, TSX with `.TO` suffix; history and fundamentals). Unofficial; can rate-limit or change.
- **Hosting: free GitHub.** A public GitHub repo; GitHub Actions runs the scanner on a schedule;
  GitHub Pages serves the static site + JSON. (Public repo = unlimited free Actions minutes and
  free Pages; the data is public market data, nothing personal.) Owner needs a free GitHub account.
- GitHub's cron is best-effort: "every 15 min" may land every 15–40 min. Accepted.
- Yahoo sometimes blocks cloud IPs. Mitigation: retries with backoff, small batches, and the
  site always keeps the **last good** data with its timestamp rather than publishing a broken scan.
- The development sandbox currently blocks Yahoo; end-to-end testing against real data needs the
  environment's network opened to Yahoo hosts (or testing on GitHub Actions itself).

## Approaches considered

- **A. Local app on the owner's computer** — most reliable with Yahoo, but only updates while the
  computer is on and the phone can only see it on home Wi-Fi. Rejected: owner checks on phone only.
- **B. Hosted static site + scheduled GitHub Actions scanner (chosen)** — reachable anywhere on the
  phone, zero cost, no server to maintain. Trade-offs: cron delays and possible Yahoo blocks,
  handled with last-good data and a visible timestamp.
- **C. Browser fetches Yahoo directly** — impossible; Yahoo blocks cross-site browser requests.

## How it works (decided)

### Scanner (Python, runs on GitHub Actions)

1. **Universe build (weekly):** US list from NASDAQ Trader symbol directory files
   (`nasdaqlisted.txt`, `otherlisted.txt`; drop ETFs/test issues, keep NYSE / NYSE American /
   NASDAQ); TSX list from the TMX company directory. Filter to common shares. Liquidity floor:
   price ≥ $2, market cap ≥ $300M, 20-day avg dollar volume ≥ $1M (builder may tune).
2. **History (nightly, after close):** 20+ years of daily OHLC, **split-adjusted, not
   dividend-adjusted** (matches how 52-week lows are quoted). Stored compactly and reused; only
   new days are appended. From it, precompute per ticker: lowest low (and its date) for each
   period *excluding today*, period high, and a downsampled series for charts.
3. **Intraday scan (every ~15 min in market hours):** batch-download today's quote / day low for
   the whole universe; flag "hit new low today" and "near low" for each period.
4. **Fundamentals (weekly, candidates only):** for any stock in any period's lists, fetch financial
   statements and compute F-Score, Z-Score, growth, D/E, FCF, yield; cache. Newly appearing
   candidates get fundamentals on the next run if missing (shown as "loading" until then).
5. **Publish:** write small JSON files (one summary per period + one detail file per candidate with
   chart series) to the Pages site; only commit/deploy if the scan succeeded and passes sanity
   checks (e.g., universe size within expected range, no price ≤ 0, lows consistent).
6. Stocks with less history than the period are excluded from that period (no "all-time low since
   IPO" mixing).

### Site (static, mobile-first)

- Single page, no build step required beyond static files; a lightweight financial chart library
  (e.g., TradingView Lightweight Charts) for sparklines/detail charts.
- Layout: period selector at top, filter chips, the two lists as cards, detail sheet on tap.
- Dark/light mode, large tap targets, works on iPhone and Android browsers; "Add to Home Screen"
  supported (installable web app with icon).
- UI is checked by rendering in a real headless browser at phone sizes and comparing against
  well-regarded finance apps' patterns.

### Accuracy checks (part of the build)

- Unit tests for low detection, period windows, split handling, F-Score and Z-Score formulas
  against hand-worked examples.
- Spot-check a sample of results against a second public source (e.g., published 52-week lows on
  another site) before declaring done.

## Decisions made after the builder review (designer's calls, owner can override)

- **Live trial first.** The first build step is a minimal scanner that runs on GitHub Actions
  against real Yahoo data, to prove Yahoo works from GitHub's servers before the UI is built.
  The rest is built on recorded sample data (fixtures), so it doesn't depend on Yahoo being up.
- **If Yahoo persistently blocks GitHub:** the page shows a clear "data is stale since …" banner
  (never silent), and the owner is told. Choosing a fallback source is then a separate decision.
  No second data adapter is built up front.
- **Repo ownership:** the repo lives in the owner's own GitHub account. They connect GitHub to
  Claude so the builder can create the repo, push, and turn on Pages/Actions. If that's not
  possible, the builder writes a click-by-click setup guide instead.
- **60-day inactivity:** GitHub turns off scheduled workflows after 60 days without repo
  activity. A small keep-alive is included so the schedule never switches itself off.
- **Markets/holidays:** scan whenever NYSE *or* TSX is open; each list uses its own exchange's
  calendar. Windows use calendar time (1Y = 365 days back), matching how chart sites count.
- **"Near low"** compares the current price with the period low *including* today's low.
- **"Sector down too?"** compares the stock's % change over the selected period with the
  median % change of same-sector stocks in the same country.
- **Liquidity floors** use each stock's own currency (USD or CAD).
- **Wealthsimple:** being listed on these exchanges is treated as "buyable on Wealthsimple". The
  page notes that a few may not be offered, so confirm in the app.

## Left to the builder

- Exact storage format for history (e.g., Parquet in an Actions cache / release asset vs. a data
  branch) — must stay within GitHub limits.
- Batch sizes, retry/backoff, concurrency.
- Exact Quality-badge rule (must be simple and shown to the user).
- Market holiday calendar source.
- Visual styling details within the layout above.
