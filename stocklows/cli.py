"""Command line entry: python -m stocklows <command>."""
from __future__ import annotations

import argparse
import logging
import sys

from . import yahoo


def cmd_probe(_args: argparse.Namespace) -> int:
    ok = True

    def report(name: str, fn):
        nonlocal ok
        try:
            msg = fn()
            print(f"OK   {name}: {msg}")
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="stocklows")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe").set_defaults(func=cmd_probe)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
