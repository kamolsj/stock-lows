"""Pure fundamental metrics: Piotroski F-Score, Altman Z-Score, KPIs, quality badge."""
from __future__ import annotations

import math
from typing import TypedDict

import pandas as pd

FINANCIAL_SECTORS = {"Financial Services", "Finance"}
MIN_F_TESTS = 7

QUALITY_RULE_TEXT = (
    "Strong: F-Score 7 or more, Altman Z above 3 (safe; not used for banks/insurers), "
    "positive P/E and positive free cash flow. "
    "Weak: F-Score 3 or less, or Altman Z below 1.8 (distress), or losing money with negative "
    "free cash flow. Mixed: everything in between. Unknown: not enough financial data."
)


class Kpis(TypedDict, total=False):
    pe: float | None
    fwd_pe: float | None
    f_score: int | None
    f_tests: int | None
    z_score: float | None
    z_zone: str | None
    rev_growth: float | None
    eps_growth: float | None
    debt_to_equity: float | None
    fcf: float | None
    fcf_yield: float | None
    div_yield: float | None
    market_cap: float | None
    sector: str
    quality: str


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _get(stmts: dict[str, pd.DataFrame], key: str, row: str, col: int) -> float | None:
    df = stmts.get(key)
    if df is None or df.empty or row not in df.index or df.shape[1] <= col:
        return None
    return _num(df.loc[row].iloc[col])


def _div(a, b) -> float | None:
    return None if a is None or b in (None, 0) else a / b


def _years(stmts) -> int:
    df = stmts.get("balance")
    return 0 if df is None else df.shape[1]


def piotroski_detail(stmts: dict[str, pd.DataFrame]) -> tuple[int | None, int]:
    """(score scaled to 0-9, number of computable tests). Score None if < 7 tests or < 2 years."""
    if _years(stmts) < 2:
        return None, 0
    g = lambda k, r, c: _get(stmts, k, r, c)
    ta = [g("balance", "Total Assets", c) for c in (0, 1)]
    ni = [g("income", "Net Income", c) for c in (0, 1)]
    cfo = g("cashflow", "Operating Cash Flow", 0)
    roa = [_div(ni[c], ta[c]) for c in (0, 1)]
    ltd = [g("balance", "Long Term Debt", c) for c in (0, 1)]
    if ltd[0] is None and ltd[1] is None and ta[0] and ta[1]:
        ltd = [0.0, 0.0]  # no long-term debt reported in either year
    lev = [_div(ltd[c], ta[c]) for c in (0, 1)]
    cr = [_div(g("balance", "Current Assets", c), g("balance", "Current Liabilities", c)) for c in (0, 1)]
    sh = [g("balance", "Ordinary Shares Number", c) for c in (0, 1)]
    rev = [g("income", "Total Revenue", c) for c in (0, 1)]
    gm = [_div(g("income", "Gross Profit", c), rev[c]) for c in (0, 1)]
    at = [_div(rev[c], ta[c]) for c in (0, 1)]

    tests: list[bool | None] = [
        None if roa[0] is None else roa[0] > 0,
        None if cfo is None else cfo > 0,
        None if None in roa else roa[0] > roa[1],
        None if cfo is None or ni[0] is None else cfo > ni[0],
        None if None in lev else lev[0] < lev[1] or lev[0] == lev[1] == 0,
        None if None in cr else cr[0] > cr[1],
        None if None in sh else sh[0] <= sh[1],
        None if None in gm else gm[0] > gm[1],
        None if None in at else at[0] > at[1],
    ]
    done = [t for t in tests if t is not None]
    if len(done) < MIN_F_TESTS:
        return None, len(done)
    passed = sum(done)
    return int(round(passed * 9 / len(done))), len(done)


def piotroski(stmts: dict[str, pd.DataFrame]) -> int | None:
    return piotroski_detail(stmts)[0]


def altman_z(stmts: dict[str, pd.DataFrame], market_cap: float | None, sector: str) -> float | None:
    if sector in FINANCIAL_SECTORS or market_cap is None:
        return None
    g = lambda r: _get(stmts, "balance", r, 0)
    ta, ca, cl = g("Total Assets"), g("Current Assets"), g("Current Liabilities")
    re_, tl = g("Retained Earnings"), g("Total Liabilities Net Minority Interest")
    ebit, sales = _get(stmts, "income", "EBIT", 0), _get(stmts, "income", "Total Revenue", 0)
    if None in (ta, ca, cl, re_, tl, ebit, sales) or not ta or not tl:
        return None
    return (1.2 * (ca - cl) / ta + 1.4 * re_ / ta + 3.3 * ebit / ta
            + 0.6 * market_cap / tl + 1.0 * sales / ta)


def z_zone(z: float | None) -> str | None:
    if z is None:
        return None
    if z > 3:
        return "safe"
    return "grey" if z >= 1.8 else "distress"


def _growth(cur, prev) -> float | None:
    return None if cur is None or prev is None or prev <= 0 else cur / prev - 1


def kpis(info: dict, stmts: dict[str, pd.DataFrame], sector: str,
         fx: dict[tuple[str, str], float] | None = None) -> Kpis:
    """KPIs. ``fx[(trade_ccy, report_ccy)]`` converts market cap into the reporting currency."""
    sector = info.get("sector") or sector or ""
    mcap = _num(info.get("marketCap"))
    trade, report = info.get("currency"), info.get("financialCurrency") or info.get("currency")
    mcap_rep = mcap
    if mcap is not None and trade and report and trade != report:
        rate = (fx or {}).get((trade, report))
        mcap_rep = mcap * rate if rate else None

    f, ftests = piotroski_detail(stmts)
    z = altman_z(stmts, mcap_rep, sector)
    fcf = _get(stmts, "cashflow", "Free Cash Flow", 0)
    if fcf is None:
        fcf = _num(info.get("freeCashflow"))
    dy = _num(info.get("dividendYield"))
    de = _num(info.get("debtToEquity"))
    k: Kpis = {
        "pe": _num(info.get("trailingPE")),
        "fwd_pe": _num(info.get("forwardPE")),
        "f_score": f, "f_tests": ftests,
        "z_score": None if z is None else round(z, 2), "z_zone": z_zone(z),
        "rev_growth": _growth(_get(stmts, "income", "Total Revenue", 0), _get(stmts, "income", "Total Revenue", 1)),
        "eps_growth": _growth(_get(stmts, "income", "Diluted EPS", 0), _get(stmts, "income", "Diluted EPS", 1)),
        "debt_to_equity": None if de is None else de / 100,
        "fcf": fcf,
        "fcf_yield": _div(fcf, mcap_rep),
        "div_yield": 0.0 if dy is None else dy / 100,
        "market_cap": mcap,
        "sector": sector,
    }
    k["quality"] = quality(k)
    return k


def quality(k: dict) -> str:
    f, zz, pe, fcf = k.get("f_score"), k.get("z_zone"), k.get("pe"), k.get("fcf")
    financial = k.get("sector") in FINANCIAL_SECTORS
    if f is None:
        return "Unknown"
    losing = pe is None or pe <= 0
    if f <= 3 or zz == "distress" or (losing and fcf is not None and fcf < 0):
        return "Weak"
    if f >= 7 and (zz == "safe" or financial) and not losing and fcf is not None and fcf > 0:
        return "Strong"
    return "Mixed"
