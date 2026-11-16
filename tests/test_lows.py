from datetime import date

import pandas as pd
import pytest

from stocklows.lows import classify, pct_from_low, pct_off_high, period_stats

TODAY = date(2026, 11, 16)


def make_hist(start="2016-01-04", end="2026-11-13", extra=None):
    idx = pd.bdate_range(start, end)
    df = pd.DataFrame({"Low": 100.0, "Close": 105.0, "Volume": 1_000_000.0}, index=idx)
    df.loc[pd.Timestamp("2026-03-02"), ["Low", "Close"]] = [50.0, 52.0]   # 1Y low
    df.loc[pd.Timestamp("2022-06-01"), ["Low", "Close"]] = [40.0, 41.0]   # 5Y low
    df.loc[pd.Timestamp("2025-01-10"), "Close"] = 150.0                    # high, outside 1Y
    for ts, low in (extra or {}).items():
        df.loc[pd.Timestamp(ts), ["Low", "Close"]] = [low, low]
    return df.sort_index()


@pytest.fixture
def stats():
    return period_stats(make_hist(), TODAY)


def test_prior_lows_per_period(stats):
    assert stats["1Y"].prior_low == 50.0
    assert stats["1Y"].prior_low_date == date(2026, 3, 2)
    assert stats["5Y"].prior_low == 40.0
    assert stats["10Y"].prior_low == 40.0


def test_new_low_when_day_low_touches_prior_low(stats):
    assert classify(stats["1Y"], day_low=50.0, price=53.0) == "new_low"


def test_not_new_low_above(stats):
    assert classify(stats["1Y"], day_low=50.01, price=50.5) == "near_low"


def test_near_low_boundary(stats):
    assert classify(stats["1Y"], day_low=51.0, price=52.5) == "near_low"
    assert classify(stats["1Y"], day_low=51.0, price=52.51) is None


def test_today_excluded_from_prior():
    s = period_stats(make_hist(end="2026-11-16", extra={"2026-11-16": 10.0}), TODAY)
    assert s["1Y"].prior_low == 50.0


def test_short_history_excluded():
    s = period_stats(make_hist(start="2023-01-03"), TODAY)
    assert set(s) == {"1Y"}


def test_twenty_year_needs_twenty_years(stats):
    assert "20Y" not in stats


def test_spark_length_le_60(stats):
    for st in stats.values():
        assert 2 <= len(st.spark) <= 60
    assert stats["1Y"].spark[-1] == 105.0


def test_period_high_and_start_close(stats):
    assert stats["1Y"].period_high == 105.0
    assert stats["5Y"].period_high == 150.0
    assert stats["1Y"].start_close == 105.0


def test_pct_helpers():
    assert pct_from_low(51.55, 50.0) == pytest.approx(0.031)
    assert pct_off_high(75.0, 100.0) == pytest.approx(-0.25)


def test_float32_tie_counts_as_new_low():
    import numpy as np
    st = period_stats(make_hist(extra={"2026-03-02": float(np.float32(12.33))}), TODAY)["1Y"]
    assert classify(st, day_low=12.33, price=12.5) == "new_low"
