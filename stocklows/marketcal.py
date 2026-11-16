"""Exchange open/closed checks (XNYS for all US listings, XTSE for TSX)."""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd


@lru_cache(maxsize=4)
def _cal(exchange: str):
    return xcals.get_calendar(exchange)


def _ts(at: datetime) -> pd.Timestamp:
    if at.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return pd.Timestamp(at).tz_convert("UTC")


def is_open(exchange: str, at: datetime) -> bool:
    return bool(_cal(exchange).is_open_on_minute(_ts(at).floor("min")))


def session_date(exchange: str, at: datetime) -> date | None:
    """Today's session date (exchange-local) if that session has opened by ``at``."""
    cal = _cal(exchange)
    ts = _ts(at)
    local_day = ts.tz_convert(cal.tz).date()
    label = pd.Timestamp(local_day)
    if not cal.is_session(label):
        return None
    return local_day if ts >= cal.session_open(label) else None


def exchange_for_symbol(symbol: str) -> str:
    return "XTSE" if symbol.endswith(".TO") else "XNYS"
