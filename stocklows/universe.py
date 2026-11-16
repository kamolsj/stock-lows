"""Universe build: listings -> common shares -> liquidity floor."""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from . import yahoo
from .config import MIN_DOLLAR_VOL, MIN_MCAP, MIN_PRICE

log = logging.getLogger(__name__)


@dataclass
class Stock:
    symbol: str          # Yahoo symbol
    name: str
    exchange: str        # NYSE | NASDAQ | NYSE American | TSX
    currency: str        # USD | CAD
    sector: str
    market_cap: float | None


_BAD_NAME = re.compile(
    r"\b(ETFs?|Funds?|Trust Units|Warrants?|Wts?|Rights|Preferred|Pr|Pfd|Units?|Un|Notes|"
    r"Debentures|Depositary Shares Representing|Acquisition Corp(oration)?|Acquisition Co(mpany)?|"
    r"Index|Portfolio|Split Corp)\b",
    re.IGNORECASE,
)
_BAD_SYMBOL = re.compile(r"(\^|\.WS|\.WT|\.PR\.|\.UN$|\.U$|\.DB|\.RT$|\.NT)")


def to_yahoo(raw_symbol: str, exchange: str) -> str:
    sym = raw_symbol.strip().upper().replace("/", "-").replace(".", "-")
    return f"{sym}.TO" if exchange == "TSX" else sym


def is_common_share(name: str, symbol: str) -> bool:
    if _BAD_SYMBOL.search(symbol.upper()):
        return False
    return not _BAD_NAME.search(name)


def _cap(v) -> float | None:
    try:
        f = float(str(v).replace(",", ""))
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def build_universe(us_rows: list[dict], tsx_rows: list[dict],
                   info_fetcher: Callable[[str], dict] = yahoo.fetch_info,
                   workers: int = 8) -> list[Stock]:
    out: dict[str, Stock] = {}
    for r in us_rows:
        if not r.get("symbol") or not is_common_share(r.get("name", ""), r["symbol"]):
            continue
        sym = to_yahoo(r["symbol"], r["exchange"])
        out.setdefault(sym, Stock(sym, r["name"], r["exchange"], "USD", r.get("sector") or "",
                                  _cap(r.get("marketCap"))))

    cands = []
    for r in tsx_rows:
        label = f"{r.get('name', '')} {r.get('instrument_name', '')}"
        if r.get("symbol") and is_common_share(label, r["symbol"]):
            cands.append((to_yahoo(r["symbol"], "TSX"), r.get("name", "")))
    cands = list(dict(cands).items())

    def enrich(item):
        sym, name = item
        try:
            info = info_fetcher(sym) or {}
        except Exception as e:
            log.warning("info failed for %s: %s", sym, e)
            return None
        if info.get("quoteType") != "EQUITY" or info.get("currency") not in ("CAD", "USD"):
            return None
        return Stock(sym, name, "TSX", info["currency"], info.get("sector") or "",
                     _cap(info.get("marketCap")))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for st in ex.map(enrich, cands):
            if st:
                out[st.symbol] = st
    return sorted(out.values(), key=lambda s: s.symbol)


def apply_liquidity(stocks: list[Stock], hist: dict[str, pd.DataFrame]) -> list[Stock]:
    kept = []
    for s in stocks:
        h = hist.get(s.symbol)
        if h is None or h.empty or s.market_cap is None or s.market_cap < MIN_MCAP:
            continue
        last20 = h.tail(20)
        if float(h["Close"].iloc[-1]) < MIN_PRICE:
            continue
        if float((last20["Close"] * last20["Volume"]).mean()) < MIN_DOLLAR_VOL:
            continue
        kept.append(s)
    return kept


def save_universe(stocks: list[Stock], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(s) for s in stocks]))


def load_universe(path: Path) -> list[Stock]:
    return [Stock(**d) for d in json.loads(path.read_text())]
