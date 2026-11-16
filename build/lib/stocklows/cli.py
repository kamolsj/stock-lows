"""Command line entry: python -m stocklows <probe|universe|nightly|fundamentals|intraday>.

Every pipeline takes --state DIR (cached between runs, not served) and --out DIR (site/data).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import yahoo
from .config import DETAIL_WITHIN_PCT, MIN_MCAP, PERIODS
from .fundamentals import kpis
from .history import HistoryStore
from .lows import PeriodStat, period_stats
from .marketcal import is_open, session_date
from .publish import build_lists, sanity_check, select_today, write_json, write_status
from .universe import apply_liquidity, build_universe, load_universe, save_universe

log = logging.getLogger("stocklows")
ET = ZoneInfo("America/New_York")
EXCHANGES = ("XNYS", "XTSE")
FUND_MAX_AGE = timedelta(days=7)
DAILY_POINTS = 400


def _read(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


# ---------------------------------------------------------------- universe
def run_universe(state: Path, us_fetch=yahoo.fetch_us_listings, tsx_fetch=yahoo.fetch_tsx_listings,
                 info_fetcher=yahoo.fetch_info) -> int:
    stocks = build_universe(us_fetch(), tsx_fetch(), info_fetcher=info_fetcher)
    stocks = [s for s in stocks if s.market_cap is not None and s.market_cap >= MIN_MCAP]
    if not stocks:
        raise RuntimeError("universe build produced no stocks")
    save_universe(stocks, Path(state) / "universe_raw.json")
    by_ex = pd.Series([s.exchange for s in stocks]).value_counts().to_dict()
    log.info("universe (pre-liquidity): %d stocks %s", len(stocks), by_ex)
    return len(stocks)


# ---------------------------------------------------------------- nightly
def _detail(sym: str, name: str, currency: str, hist: pd.DataFrame,
            stats: dict[str, PeriodStat]) -> dict:
    def pts(df: pd.DataFrame) -> list[list[float]]:
        return [[int(ts.timestamp()), round(float(c), 4), round(float(lo), 4)]
                for ts, c, lo in zip(df.index, df["Close"], df["Low"])]

    start = hist.index.max() - pd.Timedelta(days=PERIODS["20Y"] + 7)
    weekly = (hist[hist.index >= start].resample("W-FRI")
              .agg({"Close": "last", "Low": "min"}).dropna())
    return {"symbol": sym, "name": name, "currency": currency,
            "series": {"daily": pts(hist.tail(DAILY_POINTS)), "weekly": pts(weekly)},
            "lows": {p: {"low": st.prior_low, "date": st.prior_low_date.isoformat()}
                     for p, st in stats.items()}}


def run_nightly(state: Path, out: Path, today: date, downloader=yahoo.download_daily) -> int:
    state, out = Path(state), Path(out)
    raw = load_universe(state / "universe_raw.json")
    store = HistoryStore(state)
    hist = store.update([s.symbol for s in raw], today, downloader=downloader)
    store.save()

    universe = apply_liquidity(raw, hist)
    save_universe(universe, state / "universe.json")

    stats_out: dict[str, dict] = {}
    detail_set: list[str] = []
    detail_dir = out / "detail"
    detail_dir.mkdir(parents=True, exist_ok=True)
    for s in universe:
        h = hist[s.symbol]
        anchor = h.index.max().date() + timedelta(days=1)   # windows end at the last close
        st = period_stats(h, anchor)
        if not st:
            continue
        stats_out[s.symbol] = {p: v.to_dict() for p, v in st.items()}
        last = float(h["Close"].iloc[-1])
        if any(last <= v.prior_low * (1 + DETAIL_WITHIN_PCT) for v in st.values()):
            detail_set.append(s.symbol)
            write_json(detail_dir / f"{s.symbol}.json", _detail(s.symbol, s.name, s.currency, h, st))

    keep = {f"{sym}.json" for sym in detail_set}
    for f in detail_dir.glob("*.json"):
        if f.name not in keep:
            f.unlink()
    write_json(state / "stats.json", {"built": today.isoformat(), "stats": stats_out})
    write_json(state / "detail_set.json", detail_set)
    log.info("nightly: %d liquid stocks, %d with stats, %d detail files",
             len(universe), len(stats_out), len(detail_set))
    return len(stats_out)


# ---------------------------------------------------------------- fundamentals
def _fx(downloader) -> dict[tuple[str, str], float]:
    got = downloader(["CADUSD=X", "USDCAD=X"], period="5d")
    fx = {}
    if "CADUSD=X" in got:
        fx[("CAD", "USD")] = float(got["CADUSD=X"]["Close"].iloc[-1])
    if "USDCAD=X" in got:
        fx[("USD", "CAD")] = float(got["USDCAD=X"]["Close"].iloc[-1])
    return fx


def run_fundamentals(state: Path, now: datetime, info_fetcher=yahoo.fetch_info,
                     stmt_fetcher=yahoo.fetch_statements, downloader=yahoo.download_daily,
                     workers: int = 4) -> int:
    state = Path(state)
    universe = {s.symbol: s for s in load_universe(state / "universe.json")}
    wanted = [s for s in _read(state / "detail_set.json", []) if s in universe]
    cache: dict[str, dict] = _read(state / "fundamentals.json", {})
    stale = [s for s in wanted
             if s not in cache or now - datetime.fromisoformat(cache[s]["fetched"]) > FUND_MAX_AGE]
    fx = _fx(downloader) if stale else {}

    def one(sym: str):
        try:
            return sym, kpis(info_fetcher(sym), stmt_fetcher(sym), universe[sym].sector, fx=fx)
        except Exception as e:
            log.warning("fundamentals failed for %s: %s", sym, e)
            return sym, None

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for sym, k in ex.map(one, stale):
            if k is not None:
                cache[sym] = {"fetched": now.isoformat(), "kpis": k}
                done += 1
    write_json(state / "fundamentals.json", cache)
    log.info("fundamentals: %d refreshed, %d cached total", done, len(cache))
    return done


# ---------------------------------------------------------------- intraday
def run_intraday(state: Path, out: Path, now: datetime, downloader=yahoo.download_daily) -> bool:
    state, out = Path(state), Path(out)
    markets = {ex: is_open(ex, now) for ex in EXCHANGES}
    sessions = {ex: session_date(ex, now) for ex in EXCHANGES}
    if not any(sessions.values()):
        write_status(out, now, markets, ok=True, message="Markets closed")
        log.info("no session today yet; nothing to scan")
        return True

    universe = load_universe(state / "universe.json")
    raw_stats = _read(state / "stats.json", {}).get("stats", {})
    stats = {sym: {p: PeriodStat.from_dict(v) for p, v in per.items()} for sym, per in raw_stats.items()}
    fundamentals = _read(state / "fundamentals.json", {})

    try:
        bars = downloader([s.symbol for s in universe], period="5d")
    except Exception as e:
        write_status(out, now, markets, ok=False, message=f"price download failed: {e}")
        return False
    quotes, expected = select_today(bars, universe, sessions)
    lists = {p: build_lists(p, universe, stats, quotes, fundamentals) for p in PERIODS}
    errs = sanity_check(quotes, expected, lists)
    if errs:
        log.error("sanity check failed: %s", errs)
        write_status(out, now, markets, ok=False, message="; ".join(errs))
        return False

    for p, lst in lists.items():
        write_json(out / f"lows-{p}.json", {"period": p, "as_of": now.isoformat(), **lst})
    write_status(out, now, markets, ok=True, message="")
    log.info("intraday: %d quotes; %s", len(quotes),
             {p: (len(v["new_low"]), len(v["near_low"])) for p, v in lists.items()})
    return True


# ---------------------------------------------------------------- probe + main
def cmd_probe(_args) -> int:
    ok = True

    def report(name: str, fn):
        nonlocal ok
        try:
            print(f"OK   {name}: {fn()}")
        except Exception as e:
            ok = False
            print(f"FAIL {name}: {e}")

    report("us_listings", lambda: f"{len(yahoo.fetch_us_listings())} rows")
    report("tsx_listings", lambda: f"{len(yahoo.fetch_tsx_listings())} rows")

    def bars():
        got = yahoo.download_daily(["AAPL", "RY.TO", "BRK-B"], period="5d")
        if set(got) != {"AAPL", "RY.TO", "BRK-B"}:
            raise RuntimeError(f"missing symbols, got {sorted(got)}")
        return "\n" + "\n".join(f"  {s}:\n{df.tail(3).to_string()}" for s, df in got.items())
    report("daily_bars", bars)
    report("info", lambda: f"AAPL marketCap={yahoo.fetch_info('AAPL').get('marketCap')}")
    report("statements", lambda: f"RY.TO income cols={list(yahoo.fetch_statements('RY.TO')['income'].columns)[:2]}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    p = argparse.ArgumentParser(prog="stocklows")
    p.add_argument("--state", type=Path, default=Path("state"))
    p.add_argument("--out", type=Path, default=Path("out"))
    p.add_argument("cmd", choices=["probe", "universe", "nightly", "fundamentals", "intraday"])
    a = p.parse_args(argv)
    now = datetime.now(timezone.utc)
    if a.cmd == "probe":
        return cmd_probe(a)
    if a.cmd == "universe":
        run_universe(a.state)
    elif a.cmd == "nightly":
        run_nightly(a.state, a.out, now.astimezone(ET).date())
    elif a.cmd == "fundamentals":
        run_fundamentals(a.state, now)
    elif a.cmd == "intraday":
        run_intraday(a.state, a.out, now)   # failures are reported in status.json; exit 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
