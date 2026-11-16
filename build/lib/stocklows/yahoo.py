"""The ONLY module that performs network I/O.

Sources (verified live 2026-11-16):
- Prices / fundamentals: Yahoo Finance via yfinance (TSX symbols use the ``.TO`` suffix).
- US listings: NASDAQ screener API, one call per exchange (nyse, nasdaq, amex).
- TSX listings: TMX company directory JSON at www.tsx.com.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Callable, TypeVar

import pandas as pd
import requests

log = logging.getLogger(__name__)

BATCH = 200
RETRY_DELAYS = (2, 4, 8)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36", "Accept": "application/json"}
NASDAQ_SCREENER = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true&exchange={ex}"
TSX_DIRECTORY = "https://www.tsx.com/json/company-directory/search/tsx/%5E*"
US_EXCHANGES = {"nyse": "NYSE", "nasdaq": "NASDAQ", "amex": "NYSE American"}

T = TypeVar("T")


def _retry(fn: Callable[[], T], what: str) -> T:
    last: Exception | None = None
    for i, delay in enumerate((0, *RETRY_DELAYS)):
        if delay:
            time.sleep(delay)
        try:
            return fn()
        except Exception as e:  # network / parsing hiccups from upstream
            last = e
            log.warning("%s failed (attempt %d): %s", what, i + 1, e)
    raise RuntimeError(f"{what} failed after retries: {last}")


def _get_json(url: str) -> dict:
    def go() -> dict:
        r = requests.get(url, headers=UA, timeout=60)
        r.raise_for_status()
        return r.json()
    return _retry(go, f"GET {url}")


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={"Stock Splits": "Splits"})
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col not in df:
            df[col] = float("nan")
    if "Splits" not in df:
        df["Splits"] = 0.0
    df = df[["Open", "High", "Low", "Close", "Volume", "Splits"]].copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df["Splits"] = df["Splits"].fillna(0.0)
    return df.dropna(subset=["Low", "Close"])


def download_daily(symbols: list[str], start: date | None = None,
                   period: str | None = None) -> dict[str, pd.DataFrame]:
    """Split-adjusted (not dividend-adjusted) daily bars. Missing symbols are omitted."""
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), BATCH):
        batch = symbols[i:i + BATCH]
        kwargs = dict(auto_adjust=False, actions=True, group_by="ticker", threads=True,
                      progress=False, interval="1d")
        if start is not None:
            kwargs["start"] = start.isoformat()
        else:
            kwargs["period"] = period or "max"

        raw = _retry(lambda: yf.download(batch, **kwargs), f"download batch {i // BATCH}")
        if raw is None or raw.empty:
            continue
        for sym in batch:
            try:
                sub = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                continue
            sub = _normalise(sub)
            if not sub.empty:
                out[sym] = sub
    return out


def fetch_info(symbol: str) -> dict:
    import yfinance as yf
    return _retry(lambda: yf.Ticker(symbol).info or {}, f"info {symbol}")


def fetch_statements(symbol: str) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    def go() -> dict[str, pd.DataFrame]:
        t = yf.Ticker(symbol)
        return {"income": t.income_stmt, "balance": t.balance_sheet, "cashflow": t.cashflow}
    return _retry(go, f"statements {symbol}")


def fetch_us_listings() -> list[dict]:
    rows: list[dict] = []
    for ex, label in US_EXCHANGES.items():
        data = _get_json(NASDAQ_SCREENER.format(ex=ex))
        for r in (data.get("data") or {}).get("rows") or []:
            rows.append({"symbol": r.get("symbol", "").strip(), "name": r.get("name", "").strip(),
                         "marketCap": r.get("marketCap"), "sector": r.get("sector") or "",
                         "exchange": label})
    return rows


def fetch_tsx_listings() -> list[dict]:
    data = _get_json(TSX_DIRECTORY)
    rows: list[dict] = []
    for company in data.get("results") or []:
        for inst in company.get("instruments") or []:
            rows.append({"symbol": inst.get("symbol", "").strip(),
                         "name": company.get("name", "").strip(),
                         "instrument_name": inst.get("name", "").strip()})
    return rows
