import json
from pathlib import Path

import pandas as pd
import pytest

from stocklows.universe import Stock, apply_liquidity, build_universe, is_common_share, to_yahoo

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("raw,ex,want", [
    ("BRK.B", "NYSE", "BRK-B"), ("BRK/B", "NYSE", "BRK-B"), ("RCI.B", "TSX", "RCI-B.TO"),
    ("BBD/B", "TSX", "BBD-B.TO"), ("RY", "TSX", "RY.TO"), ("AAPL", "NASDAQ", "AAPL"),
])
def test_to_yahoo(raw, ex, want):
    assert to_yahoo(raw, ex) == want


@pytest.mark.parametrize("name,sym", [
    ("SPDR S&P 500 ETF Trust", "SPY"), ("Some Income Fund", "XYZ"), ("Big Trust Units", "BTU"),
    ("Amprius Technologies Inc. Warrants to purchase", "AMPX.WS"), ("Foo Corp Rights", "FOOR"),
    ("Arbor Realty Trust 6.375% Series D Cumulative Preferred Stock", "ABR^D"),
    ("Bank of America Corporation Depositary Shares Representing Preferred", "BAC^K"),
    ("Burtech Acquisition Corp II Unit", "BRKHU"), ("Enbridge 5.50% Pr", "ENB.PR.A"),
    ("Cardinal Energy Wts", "CJ.WT"), ("2028 InvGrd Bnd F Un", "IGBT.UN"),
    ("Burtech Acquisition Corp II Class A Ordinary Shares", "BRKH"),
])
def test_not_common(name, sym):
    assert is_common_share(name, sym) is False


@pytest.mark.parametrize("name,sym", [
    ("Apple Inc. Common Stock", "AAPL"), ("Berkshire Hathaway Inc.", "BRK/B"),
    ("Rogers Comm Cl B NV", "RCI.B"), ("Royal Bank of Canada", "RY"),
    ("Fundamental Global Inc. Common Stock", "FGF"),
])
def test_common(name, sym):
    assert is_common_share(name, sym) is True


def fake_info(sym):
    return {"RY.TO": {"quoteType": "EQUITY", "marketCap": 4e11, "sector": "Financial Services", "currency": "CAD"},
            "BTCQ.TO": {"quoteType": "ETF", "marketCap": 1e9, "currency": "CAD"}}.get(
        sym, {"quoteType": "EQUITY", "marketCap": 1e10, "sector": "Industrials", "currency": "CAD"})


def test_build_universe_from_fixtures():
    us = json.loads((FIX / "us_listings.json").read_text())
    tsx = json.loads((FIX / "tsx_listings.json").read_text())
    stocks = {s.symbol: s for s in build_universe(us, tsx, info_fetcher=fake_info)}
    assert "BRK-B" in stocks and stocks["BRK-B"].exchange == "NYSE" and stocks["BRK-B"].currency == "USD"
    assert "RY.TO" in stocks and stocks["RY.TO"].sector == "Financial Services"
    assert stocks["RY.TO"].currency == "CAD" and stocks["RY.TO"].exchange == "TSX"
    assert "RCI-B.TO" in stocks
    assert "BTCQ.TO" not in stocks          # ETF by quoteType
    assert not any(s.endswith(".WS") or "^" in s for s in stocks)
    assert "ENB-PR-A.TO" not in stocks


def hist(close, vol, n=25):
    idx = pd.bdate_range(end="2026-11-13", periods=n)
    return pd.DataFrame({"Low": close, "Close": close, "Volume": vol}, index=idx)


def test_apply_liquidity_floors():
    mk = lambda sym, cap: Stock(sym, sym, "NYSE", "USD", "Tech", cap)
    stocks = [mk("OK", 5e8), mk("CHEAP", 5e8), mk("SMALL", 299_999_999), mk("THIN", 5e8), mk("NOHIST", 5e8)]
    h = {"OK": hist(10.0, 200_000.0), "CHEAP": hist(1.99, 10_000_000.0),
         "SMALL": hist(10.0, 200_000.0), "THIN": hist(10.0, 99_999.9)}
    kept = [s.symbol for s in apply_liquidity(stocks, h)]
    assert kept == ["OK"]
