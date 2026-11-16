"""Pure period statistics and low detection. No I/O."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Literal

import numpy as np
import pandas as pd

from .config import NEAR_PCT, PERIODS

SPARK_POINTS = 60


@dataclass
class PeriodStat:
    prior_low: float
    prior_low_date: date
    period_high: float
    start_close: float
    spark: list[float]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["prior_low_date"] = self.prior_low_date.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PeriodStat":
        return cls(d["prior_low"], date.fromisoformat(d["prior_low_date"]), d["period_high"],
                   d["start_close"], list(d["spark"]))


def _spark(closes: pd.Series) -> list[float]:
    n = len(closes)
    if n <= SPARK_POINTS:
        vals = closes.to_numpy()
    else:
        pos = np.linspace(0, n - 1, SPARK_POINTS).round().astype(int)
        vals = closes.to_numpy()[pos]
    return [round(float(v), 4) for v in vals]


def period_stats(hist: pd.DataFrame, today: date) -> dict[str, PeriodStat]:
    """Stats per period over [today - days, yesterday]; omits periods lacking full history."""
    if hist.empty:
        return {}
    past = hist[hist.index < pd.Timestamp(today)]
    if past.empty:
        return {}
    first = past.index.min().date()
    out: dict[str, PeriodStat] = {}
    for name, days in PERIODS.items():
        start = today - timedelta(days=days)
        if first > start:
            continue
        win = past[past.index >= pd.Timestamp(start)]
        if win.empty:
            continue
        low_ts = win["Low"].idxmin()
        out[name] = PeriodStat(
            prior_low=float(win["Low"].min()),
            prior_low_date=low_ts.date(),
            period_high=float(win["Close"].max()),
            start_close=float(win["Close"].iloc[0]),
            spark=_spark(win["Close"]),
        )
    return out


def classify(stat: PeriodStat, day_low: float, price: float) -> Literal["new_low", "near_low"] | None:
    if day_low <= stat.prior_low:
        return "new_low"
    period_low = min(stat.prior_low, day_low)
    if price <= period_low * (1 + NEAR_PCT) + 1e-9:
        return "near_low"
    return None


def pct_from_low(price: float, period_low: float) -> float:
    return price / period_low - 1


def pct_off_high(price: float, period_high: float) -> float:
    return price / period_high - 1
