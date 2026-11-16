"""'Sector down too?' — did the whole sector fall, or just this stock?"""
from __future__ import annotations

import statistics

SECTOR_DOWN = -0.10
MIN_PEERS = 5


def sector_check(stock_pct: float, sector_pcts: list[float]) -> dict:
    if len(sector_pcts) < MIN_PEERS:
        return {"stock_pct": stock_pct, "sector_median_pct": None, "verdict": "unknown"}
    med = float(statistics.median(sector_pcts))
    return {"stock_pct": stock_pct, "sector_median_pct": med,
            "verdict": "sector" if med <= SECTOR_DOWN + 1e-12 else "stock"}
