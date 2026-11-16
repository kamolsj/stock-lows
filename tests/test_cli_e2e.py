import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from stocklows import cli

MON = date(2026, 11, 16)
NOW = datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc)  # 11:00 ET, both markets open


def long_hist(base_low, end="2026-11-13"):
    idx = pd.bdate_range("2005-01-03", end)
    close = 66 + 0.5 * np.sin(np.arange(len(idx)) / 20)   # hovers near 66; lows ~65
    df = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close,
                       "Volume": 1e6, "Splits": 0.0}, index=idx)
    df.loc[pd.Timestamp("2026-06-01"), "Low"] = base_low   # 1Y low
    return df


US = [{"symbol": s, "name": f"{s} Common Stock", "marketCap": "5000000000", "sector": "Tech",
       "exchange": "NYSE"} for s in ["NEWL", "NEAR", "FAR", "P1", "P2", "P3", "P4", "P5"]]
TSX = [{"symbol": "RY", "name": "Royal Bank of Canada", "instrument_name": "Royal Bank of Canada"}]
LOWS = {"NEWL": 60.0, "NEAR": 60.0, "FAR": 60.0, "P1": 60, "P2": 60, "P3": 60, "P4": 60, "P5": 60, "RY.TO": 60.0}
TODAY_BARS = {"NEWL": (59.0, 61.0), "NEAR": (61.0, 62.0), "FAR": (90.0, 95.0), "RY.TO": (61.0, 61.5)}


def fake_download(symbols, start=None, period=None):
    out = {}
    for s in symbols:
        if s.endswith("=X"):
            out[s] = pd.DataFrame({"Open": 0.72, "High": 0.72, "Low": 0.72, "Close": 0.72, "Volume": 0.0,
                                   "Splits": 0.0}, index=pd.DatetimeIndex([pd.Timestamp("2026-11-13")]))
            continue
        if period == "5d":
            low, close = TODAY_BARS.get(s, (100.0, 101.0))
            out[s] = pd.DataFrame({"Open": close, "High": close, "Low": [101.0, low], "Close": [101.0, close],
                                   "Volume": 1e6, "Splits": 0.0},
                                  index=pd.DatetimeIndex([pd.Timestamp("2026-11-13"), pd.Timestamp(MON)]))
        else:
            out[s] = long_hist(LOWS[s])
    return out


def fake_info(sym):
    return {"quoteType": "EQUITY", "currency": "CAD", "financialCurrency": "CAD", "marketCap": 4e11,
            "sector": "Financial Services", "trailingPE": 12.0}


def fake_stmts(sym):
    return {"income": pd.DataFrame(), "balance": pd.DataFrame(), "cashflow": pd.DataFrame()}


def test_full_pipeline(tmp_path):
    state, out = tmp_path / "state", tmp_path / "out"
    cli.run_universe(state, us_fetch=lambda: US, tsx_fetch=lambda: TSX, info_fetcher=fake_info)
    cli.run_nightly(state, out, MON, downloader=fake_download)
    cli.run_fundamentals(state, NOW, info_fetcher=fake_info, stmt_fetcher=fake_stmts, downloader=fake_download)
    cli.run_intraday(state, out, NOW, downloader=fake_download)

    st = json.loads((out / "status.json").read_text())
    assert st["ok"] is True, st
    l1 = json.loads((out / "lows-1Y.json").read_text())
    assert [r["symbol"] for r in l1["new_low"]] == ["NEWL"]
    assert {r["symbol"] for r in l1["near_low"]} == {"NEAR", "RY.TO"}
    ry = next(r for r in l1["near_low"] if r["symbol"] == "RY.TO")
    assert ry["currency"] == "CAD" and ry["pe"] == 12.0
    assert (out / "detail" / "NEWL.json").exists()
    d = json.loads((out / "detail" / "NEWL.json").read_text())
    assert d["lows"]["1Y"]["low"] == 60.0 and len(d["series"]["daily"]) == 400
    assert len(d["series"]["weekly"]) > 1000
    for p in ("5Y", "10Y", "20Y"):
        assert (out / f"lows-{p}.json").exists()


def test_intraday_when_closed_keeps_lists(tmp_path):
    state, out = tmp_path / "state", tmp_path / "out"
    cli.run_universe(state, us_fetch=lambda: US, tsx_fetch=lambda: TSX, info_fetcher=fake_info)
    cli.run_nightly(state, out, MON, downloader=fake_download)
    sat = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
    cli.run_intraday(state, out, sat, downloader=fake_download)
    st = json.loads((out / "status.json").read_text())
    assert st["markets"] == {"XNYS": False, "XTSE": False}
    assert not (out / "lows-1Y.json").exists()
