"""Turn quotes + stats + KPIs into the site's JSON, with sanity checks."""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .config import MAX_MISSING_FRAC
from .lows import PeriodStat, classify, pct_from_low, pct_off_high
from .marketcal import exchange_for_symbol
from .sectors import sector_check
from .universe import Stock

KPI_KEYS = ("pe", "fwd_pe", "f_score", "f_tests", "z_score", "z_zone", "rev_growth", "eps_growth",
            "debt_to_equity", "fcf", "fcf_yield", "div_yield", "quality")
ROW_KEYS = ("symbol", "name", "exchange", "currency", "price", "day_low", "period_low",
            "period_low_date", "pct_from_low", "pct_off_high", "market_cap", "sector", "spark",
            *KPI_KEYS, "sector_check")

Quote = dict  # {"date": date, "low": float, "price": float}


def select_today(bars: dict[str, pd.DataFrame], universe: list[Stock],
                 sessions: dict[str, date | None]) -> tuple[dict[str, Quote], int]:
    """Quotes whose last bar is today's session for that stock's exchange.

    Returns (quotes, expected) where expected counts stocks whose exchange has a session today.
    Stocks on an exchange with no session (pre-open, holiday) are skipped silently.
    """
    quotes: dict[str, Quote] = {}
    expected = 0
    for s in universe:
        sess = sessions.get(exchange_for_symbol(s.symbol))
        if sess is None:
            continue
        expected += 1
        df = bars.get(s.symbol)
        if df is None or df.empty:
            continue
        last = df.iloc[-1]
        if df.index[-1].date() != sess or pd.isna(last["Low"]) or pd.isna(last["Close"]):
            continue
        quotes[s.symbol] = {"date": sess, "low": float(last["Low"]), "price": float(last["Close"])}
    return quotes, expected


def sanity_check(quotes: dict[str, Quote], expected: int, lists: dict[str, dict]) -> list[str]:
    errs: list[str] = []
    if expected and (1 - len(quotes) / expected) > MAX_MISSING_FRAC + 1e-9:
        errs.append(f"too many missing quotes: got {len(quotes)} of {expected}")
    bad = [s for s, q in quotes.items() if q["price"] <= 0 or q["low"] <= 0]
    if bad:
        errs.append(f"non-positive price for {len(bad)} symbols, e.g. {bad[:3]}")
    for period, lst in lists.items():
        for r in lst.get("new_low", []):
            if r["day_low"] > r["period_low"] + 1e-9:
                errs.append(f"inconsistent new low {r['symbol']} {period}")
    return errs


def _country(s: Stock) -> str:
    return "CA" if s.exchange == "TSX" else "US"


def build_lists(period: str, universe: list[Stock], stats: dict[str, dict[str, PeriodStat]],
                quotes: dict[str, Quote], fundamentals: dict[str, dict]) -> dict:
    # Sector peers: % change over the period for every stock with stats.
    peers: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for s in universe:
        st = stats.get(s.symbol, {}).get(period)
        if st is None or not s.sector or st.start_close <= 0:
            continue
        px = quotes[s.symbol]["price"] if s.symbol in quotes else st.spark[-1]
        peers[(_country(s), s.sector)][s.symbol] = px / st.start_close - 1

    new_low, near_low = [], []
    for s in universe:
        st = stats.get(s.symbol, {}).get(period)
        q = quotes.get(s.symbol)
        if st is None or q is None:
            continue
        kind = classify(st, q["low"], q["price"])
        if kind is None:
            continue
        is_new = kind == "new_low"
        period_low = min(st.prior_low, q["low"])
        k = (fundamentals.get(s.symbol) or {}).get("kpis") or {}
        group = peers.get((_country(s), s.sector), {})
        stock_pct = q["price"] / st.start_close - 1 if st.start_close > 0 else 0.0
        row = {
            "symbol": s.symbol, "name": s.name, "exchange": s.exchange, "currency": s.currency,
            "price": round(q["price"], 4), "day_low": round(q["low"], 4),
            "period_low": round(period_low, 4),
            "period_low_date": (q["date"] if is_new else st.prior_low_date).isoformat(),
            "pct_from_low": round(pct_from_low(q["price"], period_low), 5),
            "pct_off_high": round(pct_off_high(q["price"], max(st.period_high, q["price"])), 5),
            "market_cap": k.get("market_cap") or s.market_cap, "sector": s.sector,
            "spark": [*st.spark, round(q["price"], 4)],
            **{key: k.get(key) for key in KPI_KEYS},
            "sector_check": sector_check(stock_pct, [v for sym, v in group.items() if sym != s.symbol]),
        }
        (new_low if is_new else near_low).append(row)
    key = lambda r: (r["pct_from_low"], r["symbol"])
    return {"new_low": sorted(new_low, key=key), "near_low": sorted(near_low, key=key)}


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":"), allow_nan=False, default=str))
    os.replace(tmp, path)


def write_status(out: Path, now: datetime, markets: dict[str, bool], ok: bool, message: str) -> dict:
    path = Path(out) / "status.json"
    prev = {}
    if path.exists():
        try:
            prev = json.loads(path.read_text())
        except json.JSONDecodeError:
            prev = {}
    st = {"as_of": now.isoformat(), "last_success": now.isoformat() if ok else prev.get("last_success"),
          "markets": markets, "ok": ok, "message": message}
    write_json(path, st)
    return st
