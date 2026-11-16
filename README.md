# Stock Lows

A phone-friendly page that lists **NYSE, NASDAQ, NYSE American and TSX** stocks that
**hit their lowest price of the last 1, 5, 10 or 20 years today**, plus those **within 5%** of
that low, with charts and quality signals (P/E, Piotroski F-Score, Altman Z-Score, growth,
debt, free cash flow, dividend, and a "sector down too?" check).

- Prices are free Yahoo Finance data, about 15 minutes delayed.
- The page updates about every 15 minutes while markets are open (GitHub's timer can run late,
  so sometimes 20–40 minutes).
- Penny stocks are left out: price ≥ $2, market cap ≥ $300M, and ≥ $1M traded per day on average.
- For research only, not investment advice. A few listed stocks may not be offered on
  Wealthsimple, so confirm in the app.

## How it works

```
GitHub Actions (free)                                 GitHub Pages (free)
  Saturday  : build stock list (NASDAQ + TMX)          gh-pages branch
  Weeknights: 20y price history, charts, fundamentals  ─► index.html + data/*.json ─► your phone
  Every 15m : today's prices → who hit a low          ─┘
```

The page always shows when its prices are from. If an update fails, it keeps the last good data
and shows a red **"Data is stale since …"** banner, so old data never passes for current.

## One-time setup (about 15 minutes)

1. **Create a free GitHub account** at <https://github.com/signup> if you don't have one.
2. **Create a new repository**: <https://github.com/new>
   - Name: `stock-lows`
   - Visibility: **Public** (this keeps the scheduled updates and the web page free; it holds only
     public market data, nothing personal)
   - Leave "Add a README" unticked, then **Create repository**.
3. **Upload this project**: on the empty repository page, click **"uploading an existing file"**,
   drag in everything in this folder **including the hidden `.github` folder**, then **Commit changes**.
   (Or, if you use git: `git remote add origin https://github.com/YOU/stock-lows.git` and `git push -u origin main`.)
4. **Allow the workflow to publish**: repository **Settings → Actions → General → Workflow permissions →
   "Read and write permissions" → Save**.
5. **Run the first scan**: **Actions** tab → if asked, click **"I understand my workflows, go ahead and enable them"**
   → choose **scan** on the left → **Run workflow** → mode **weekly** → **Run workflow**.
   The first run downloads 20 years of prices for ~3,000 stocks and takes roughly 30–60 minutes.
   Wait for the green check.
6. **Turn on the web page**: **Settings → Pages → Build and deployment → Source: "Deploy from a branch"
   → Branch: `gh-pages`, folder `/ (root)` → Save**. After a minute the page is live at
   `https://YOU.github.io/stock-lows/`.
7. **On your phone**: open that link.
   - iPhone (Safari): Share → **Add to Home Screen**.
   - Android (Chrome): ⋮ menu → **Add to Home screen**.

That's it. From then on it updates on its own during market hours.

### Check it's working

- The top of the page says *"Prices as of <time> ET"*. During market hours that time should be
  within about 15–40 minutes of now.
- **Actions** tab: recent **scan** runs show green checks.

## Running locally (optional, for developers)

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q                                   # unit + pipeline tests
.venv/bin/python -m stocklows probe                   # check the data sources respond
.venv/bin/python -m stocklows universe                # stock list   -> state/
.venv/bin/python -m stocklows nightly                 # history etc. -> state/, out/detail/
.venv/bin/python -m stocklows fundamentals
.venv/bin/python -m stocklows intraday                # lists        -> out/
node tools/ui_check.mjs                               # phone screenshots -> site-screens/
node tools/ui_check.mjs --real out                    # same, on real data
```

## What the numbers mean

| Signal | Meaning |
|---|---|
| **Hit a new low today** | Today's lowest trade was at or below the lowest daily low of the whole period (split-adjusted). It counts even if the price bounced back later. |
| **Near the low** | Current price is within 5% of the period low. |
| **P/E** | Price ÷ last 12 months' earnings. Negative or missing means the company lost money. |
| **Piotroski F-Score** (0–9) | Nine checks on profitability, debt and efficiency. 7+ is strong; 3 or less is weak. For banks, some checks don't apply, so the score is scaled from the checks that do (shown on the detail page). |
| **Altman Z-Score** | Bankruptcy-risk gauge: above 3 is safe, 1.8–3 is a grey zone, below 1.8 is distress. Not meaningful for banks and insurers. |
| **Sector down too?** | Compares the stock's drop over the period with the median drop of its sector peers in the same country. If the whole sector fell, the drop is more likely timing or market mood. If only this stock fell, check the news. |
| **Quality badge** | **Strong**: F ≥ 7, Z safe (or a financial company), positive P/E and positive free cash flow. **Weak**: F ≤ 3, or Z in distress, or losing money with negative free cash flow. **Mixed**: everything in between. |
