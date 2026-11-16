from datetime import date, datetime
from zoneinfo import ZoneInfo

from stocklows.marketcal import exchange_for_symbol, is_open, session_date

ET = ZoneInfo("America/New_York")


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


def test_nyse_open_monday_morning():
    assert is_open("XNYS", at(2026, 11, 16, 10)) is True


def test_nyse_closed_thanksgiving():
    assert is_open("XNYS", at(2026, 11, 26, 10)) is False


def test_tsx_open_us_thanksgiving():
    assert is_open("XTSE", at(2026, 11, 26, 10)) is True


def test_nyse_closed_before_open():
    assert is_open("XNYS", at(2026, 11, 16, 9)) is False


def test_session_date_none_before_open():
    assert session_date("XNYS", at(2026, 11, 16, 9)) is None


def test_session_date_after_close_is_today():
    assert session_date("XNYS", at(2026, 11, 16, 18)) == date(2026, 11, 16)


def test_session_date_weekend_none():
    assert session_date("XTSE", at(2026, 11, 15, 12)) is None


def test_exchange_for_symbol():
    assert exchange_for_symbol("RY.TO") == "XTSE"
    assert exchange_for_symbol("AAPL") == "XNYS"
