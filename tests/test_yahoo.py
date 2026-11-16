import pandas as pd
import yfinance

from stocklows import yahoo


def frame(symbols, ok):
    idx = pd.DatetimeIndex([pd.Timestamp("2026-11-13")])
    cols = {}
    for s in symbols:
        for c in ("Open", "High", "Low", "Close", "Volume"):
            cols[(s, c)] = [10.0 if s in ok else float("nan")]
    return pd.DataFrame(cols, index=idx)


def test_missing_symbols_are_retried(monkeypatch):
    calls = []

    def fake(tickers, **kw):
        calls.append(list(tickers))
        ok = {"A"} if len(calls) == 1 else set(tickers)
        return frame(tickers, ok)

    monkeypatch.setattr(yfinance, "download", fake)
    monkeypatch.setattr(yahoo, "RETRY_MISSING_DELAYS", (0,))
    got = yahoo.download_daily(["A", "B", "C"], period="5d")
    assert set(got) == {"A", "B", "C"}
    assert calls[1] == ["B", "C"]
