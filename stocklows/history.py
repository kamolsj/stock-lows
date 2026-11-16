"""Parquet-backed daily history (split-adjusted Low/Close/Volume per symbol)."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Callable

import pandas as pd

from . import yahoo

log = logging.getLogger(__name__)
COLS = ["Low", "Close", "Volume"]
READJUST_RATIO = 0.25   # overlap-day close moved >25% between downloads => history was re-adjusted
Downloader = Callable[..., dict[str, pd.DataFrame]]


class HistoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.file = self.path / "history.parquet"
        self.data: dict[str, pd.DataFrame] | None = None

    def load(self) -> dict[str, pd.DataFrame]:
        if self.data is not None:
            return self.data
        self.data = {}
        if self.file.exists():
            long = pd.read_parquet(self.file)
            for sym, g in long.groupby("symbol", sort=False):
                df = g.set_index(pd.DatetimeIndex(g["date"]))[COLS].sort_index()
                df.index.name = None
                self.data[str(sym)] = df
        return self.data

    def save(self) -> None:
        data = self.load()
        self.path.mkdir(parents=True, exist_ok=True)
        frames = []
        for sym, df in data.items():
            f = df[COLS].copy()
            f["date"] = f.index
            f["symbol"] = sym
            frames.append(f)
        long = (pd.concat(frames, ignore_index=True) if frames
                else pd.DataFrame(columns=["symbol", "date", *COLS]))
        long = long.astype({"Low": "float32", "Close": "float32", "Volume": "float64"})
        tmp = self.file.with_suffix(".tmp")
        long[["symbol", "date", *COLS]].to_parquet(tmp, index=False, compression="zstd")
        tmp.replace(self.file)

    def update(self, symbols: list[str], today: date,
               downloader: Downloader = yahoo.download_daily) -> dict[str, pd.DataFrame]:
        data = self.load()
        fresh = [s for s in symbols if s not in data]
        if fresh:
            for sym, df in downloader(fresh, period="max").items():
                data[sym] = df[COLS].copy()

        by_start: dict[date, list[str]] = defaultdict(list)
        for s in symbols:
            if s in data and s not in fresh and not data[s].empty:
                by_start[data[s].index.max().date()].append(s)

        split_syms: list[str] = []
        for start, group in by_start.items():
            got = downloader(group, start=start)
            for sym, new in got.items():
                last = data[sym].index.max()
                newer = new[new.index > last]
                readjusted = False
                if last in new.index:
                    old_c, new_c = float(data[sym].loc[last, "Close"]), float(new.loc[last, "Close"])
                    readjusted = old_c > 0 and abs(new_c / old_c - 1) > READJUST_RATIO
                if readjusted or (newer.get("Splits", pd.Series(dtype=float)).fillna(0) != 0).any():
                    split_syms.append(sym)
                    continue
                merged = pd.concat([data[sym], new[COLS]])
                data[sym] = merged[~merged.index.duplicated(keep="last")].sort_index()

        if split_syms:
            log.info("split detected, full refresh: %s", split_syms)
            for sym, df in downloader(split_syms, period="max").items():
                data[sym] = df[COLS].copy()
        return data
