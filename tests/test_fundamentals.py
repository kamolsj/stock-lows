import pandas as pd
import pytest

from stocklows.fundamentals import QUALITY_RULE_TEXT, altman_z, kpis, piotroski, quality, z_zone

COLS = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")]


def stmts(cur, prev):
    def frame(keys):
        return pd.DataFrame({COLS[0]: [cur.get(k) for k in keys], COLS[1]: [prev.get(k) for k in keys]},
                            index=keys, dtype=float)
    return {"income": frame(["Net Income", "Total Revenue", "Gross Profit", "EBIT", "Diluted EPS"]),
            "balance": frame(["Total Assets", "Current Assets", "Current Liabilities", "Long Term Debt",
                              "Retained Earnings", "Total Liabilities Net Minority Interest",
                              "Ordinary Shares Number"]),
            "cashflow": frame(["Operating Cash Flow", "Free Cash Flow"])}


CUR = {"Net Income": 100, "Total Assets": 1000, "Operating Cash Flow": 150, "Long Term Debt": 200,
       "Current Assets": 400, "Current Liabilities": 200, "Ordinary Shares Number": 100,
       "Total Revenue": 800, "Gross Profit": 400, "EBIT": 150, "Retained Earnings": 300,
       "Total Liabilities Net Minority Interest": 600, "Free Cash Flow": 60, "Diluted EPS": 1.0}
PREV = {"Net Income": 80, "Total Assets": 1000, "Operating Cash Flow": 120, "Long Term Debt": 250,
        "Current Assets": 380, "Current Liabilities": 200, "Ordinary Shares Number": 100,
        "Total Revenue": 820, "Gross Profit": 420, "EBIT": 140, "Retained Earnings": 250,
        "Total Liabilities Net Minority Interest": 620, "Free Cash Flow": 50, "Diluted EPS": 0.8}


def test_piotroski_hand_worked_seven():
    # ROA .10>0 P | CFO>0 P | dROA .10>.08 P | CFO 150>NI 100 P | LTD/TA .20<.25 P
    # CR 2.0>1.9 P | shares 100<=100 P | GM .500<.512 F | turnover .80<.82 F  => 7
    assert piotroski(stmts(CUR, PREV)) == 7


def test_piotroski_needs_two_years():
    s = stmts(CUR, PREV)
    for k in s:
        s[k] = s[k][[COLS[0]]]
    assert piotroski(s) is None


def test_piotroski_bank_without_gross_margin_or_current_ratio_scaled():
    cur = {k: v for k, v in CUR.items() if k not in ("Gross Profit", "Current Assets", "Current Liabilities")}
    prev = {k: v for k, v in PREV.items() if k not in ("Gross Profit", "Current Assets", "Current Liabilities")}
    # 7 tests computable, 6 pass (turnover fails) -> round(6 * 9 / 7) = 8
    assert piotroski(stmts(cur, prev)) == 8


def test_altman_z_hand_worked():
    # 1.2*.2 + 1.4*.3 + 3.3*.15 + 0.6*1295/600 + 1.0*.8 = 3.25
    z = altman_z(stmts(CUR, PREV), market_cap=1295, sector="Industrials")
    assert z == pytest.approx(3.25, abs=0.01)
    assert z_zone(z) == "safe"


def test_altman_none_for_financials():
    assert altman_z(stmts(CUR, PREV), 1295, "Financial Services") is None
    assert altman_z(stmts(CUR, PREV), 1295, "Finance") is None


def test_z_zone_boundaries():
    assert z_zone(1.79) == "distress"
    assert z_zone(1.8) == "grey"
    assert z_zone(3.0) == "grey"
    assert z_zone(3.01) == "safe"
    assert z_zone(None) is None


def test_kpis_from_info_and_statements():
    info = {"trailingPE": 12.5, "forwardPE": 11.0, "marketCap": 1295, "sector": "Industrials",
            "dividendYield": 2.14, "debtToEquity": 107.449, "currency": "USD", "financialCurrency": "USD"}
    k = kpis(info, stmts(CUR, PREV), "Industrials")
    assert k["pe"] == 12.5 and k["fwd_pe"] == 11.0
    assert k["f_score"] == 7 and k["z_zone"] == "safe"
    assert k["rev_growth"] == pytest.approx(800 / 820 - 1)
    assert k["eps_growth"] == pytest.approx(0.25)
    assert k["debt_to_equity"] == pytest.approx(1.07449)
    assert k["div_yield"] == pytest.approx(0.0214)
    assert k["fcf"] == 60 and k["fcf_yield"] == pytest.approx(60 / 1295)


def test_kpis_currency_mismatch_uses_fx():
    info = {"marketCap": 1295 * 1.4, "currency": "CAD", "financialCurrency": "USD", "sector": "Industrials"}
    k = kpis(info, stmts(CUR, PREV), "Industrials", fx={("CAD", "USD"): 1 / 1.4})
    assert k["z_score"] == pytest.approx(3.25, abs=0.01)
    assert k["fcf_yield"] == pytest.approx(60 / 1295)
    k2 = kpis(info, stmts(CUR, PREV), "Industrials", fx={})
    assert k2["z_score"] is None and k2["fcf_yield"] is None


def base(**kw):
    k = {"pe": 10.0, "f_score": 7, "z_zone": "safe", "fcf": 1.0, "sector": "Industrials"}
    k.update(kw)
    return k


@pytest.mark.parametrize("kw,want", [
    ({}, "Strong"),
    ({"z_zone": None, "sector": "Financial Services"}, "Strong"),
    ({"f_score": None}, "Unknown"),
    ({"f_score": 3}, "Weak"),
    ({"z_zone": "distress"}, "Weak"),
    ({"pe": None, "fcf": -5.0}, "Weak"),
    ({"pe": -4.0, "fcf": -5.0}, "Weak"),
    ({"f_score": 6}, "Mixed"),
    ({"z_zone": "grey"}, "Mixed"),
    ({"pe": None, "fcf": 2.0}, "Mixed"),
])
def test_quality_rule(kw, want):
    assert quality(base(**kw)) == want


def test_rule_text_mentions_thresholds():
    assert "7" in QUALITY_RULE_TEXT and "Z" in QUALITY_RULE_TEXT
