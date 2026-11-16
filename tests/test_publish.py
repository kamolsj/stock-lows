import json
from datetime import date, datetime, timezone

import pandas as pd

from stocklows.lows import PeriodStat
from stocklows.publish import ROW_KEYS, build_lists, sanity_check, select_today, write_status
from stocklows.universe import Stock

MON = date(2026, 11, 16)


def stock(sym, exch="NYSE", sector="Tech"):
    return Stock(sym, sym + " Inc", exch, "CAD" if exch == "TSX" else "USD", sector, 1e9)


def bar(d, low, close):
    return pd.DataFrame({"Low": [low], "Close": [close], "Volume": [1e6], "Open": [close],
                         "High": [close], "Splits": [0.0]}, index=pd.DatetimeIndex([pd.Timestamp(d)]))


def stat(low=50.0):
    return PeriodStat(prior_low=low, prior_low_date=date(2026, 3, 2), period_high=100.0,
                      start_close=80.0, spark=[80.0, 60.0, 55.0])


def test_partial_batch_over_20pct_blocks_publish():
    uni = [stock(f"S{i}") for i in range(10)]
    bars = {f"S{i}": bar(MON, 60, 61) for i in range(7)}  # 30% missing
    quotes, expected = select_today(bars, uni, {"XNYS": MON, "XTSE": MON})
    errs = sanity_check(quotes, expected, {})
    assert any("missing" in e for e in errs)


def test_twenty_pct_missing_is_ok():
    uni = [stock(f"S{i}") for i in range(10)]
    bars = {f"S{i}": bar(MON, 60, 61) for i in range(8)}
    quotes, expected = select_today(bars, uni, {"XNYS": MON, "XTSE": MON})
    assert sanity_check(quotes, expected, {}) == []


def test_holiday_bars_skipped():
    thx = date(2026, 11, 26)
    uni = [stock("AAA"), stock("RY.TO", "TSX")]
    bars = {"AAA": bar(date(2026, 11, 25), 40, 41), "RY.TO": bar(thx, 40, 41)}
    quotes, expected = select_today(bars, uni, {"XNYS": None, "XTSE": thx})
    assert set(quotes) == {"RY.TO"} and expected == 1
    lists = build_lists("1Y", uni, {"AAA": {"1Y": stat()}, "RY.TO": {"1Y": stat()}}, quotes, {})
    assert [r["symbol"] for r in lists["new_low"]] == ["RY.TO"]


def test_preopen_no_flags():
    uni = [stock("AAA")]
    bars = {"AAA": bar(date(2026, 11, 13), 40, 41)}   # Friday's bar on Monday pre-open
    quotes, expected = select_today(bars, uni, {"XNYS": None, "XTSE": None})
    assert quotes == {} and expected == 0
    lists = build_lists("1Y", uni, {"AAA": {"1Y": stat()}}, quotes, {})
    assert lists["new_low"] == [] and lists["near_low"] == []


def test_stale_bar_while_open_counts_missing():
    uni = [stock("AAA")]
    quotes, expected = select_today({"AAA": bar(date(2026, 11, 13), 40, 41)}, uni, {"XNYS": MON, "XTSE": MON})
    assert quotes == {} and expected == 1
    assert sanity_check(quotes, expected, {})


def test_nonpositive_price_and_inconsistent_low_rejected():
    errs = sanity_check({"A": {"date": MON, "low": 0.0, "price": 0.0}}, 1, {})
    assert any("price" in e for e in errs)
    bad = {"1Y": {"new_low": [{"symbol": "X", "day_low": 51.0, "period_low": 50.0}], "near_low": []}}
    assert any("inconsistent" in e for e in sanity_check({"X": {"date": MON, "low": 51, "price": 52}}, 1, bad))


def test_row_shape_and_sorting():
    uni = [stock("AAA"), stock("BBB"), stock("CCC")] + [stock(f"P{i}") for i in range(5)]
    stats = {s.symbol: {"1Y": stat()} for s in uni}
    quotes = {"AAA": {"date": MON, "low": 49.0, "price": 51.0},
              "BBB": {"date": MON, "low": 50.0, "price": 50.5},
              "CCC": {"date": MON, "low": 51.0, "price": 52.0}}
    quotes.update({f"P{i}": {"date": MON, "low": 70.0, "price": 70.0} for i in range(5)})
    fund = {"AAA": {"kpis": {"pe": 9.0, "f_score": 8, "quality": "Strong"}}}
    lists = build_lists("1Y", uni, stats, quotes, fund)
    assert [r["symbol"] for r in lists["new_low"]] == ["BBB", "AAA"]   # closest to low first
    assert [r["symbol"] for r in lists["near_low"]] == ["CCC"]
    row = lists["new_low"][1]
    assert set(ROW_KEYS) <= set(row)
    assert row["period_low"] == 49.0 and row["pe"] == 9.0 and row["quality"] == "Strong"
    assert lists["near_low"][0]["quality"] is None
    assert row["sector_check"]["verdict"] == "sector"   # peers down 12.5%


def test_failed_scan_keeps_previous_lists(tmp_path):
    (tmp_path / "lows-1Y.json").write_text('{"keep": true}')
    t1 = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)
    write_status(tmp_path, t1, {"XNYS": True, "XTSE": True}, ok=True, message="")
    t2 = datetime(2026, 11, 16, 15, 15, tzinfo=timezone.utc)
    write_status(tmp_path, t2, {"XNYS": True, "XTSE": True}, ok=False, message="boom")
    st = json.loads((tmp_path / "status.json").read_text())
    assert st["ok"] is False and st["last_success"] == t1.isoformat() and st["as_of"] == t2.isoformat()
    assert json.loads((tmp_path / "lows-1Y.json").read_text()) == {"keep": True}
