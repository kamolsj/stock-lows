"""Project-wide constants (see Global Constraints in the plan)."""

PERIODS: dict[str, int] = {"1Y": 365, "5Y": 1826, "10Y": 3652, "20Y": 7305}
NEAR_PCT = 0.05
MIN_PRICE = 2
MIN_MCAP = 300_000_000
MIN_DOLLAR_VOL = 1_000_000
STALE_MINUTES = 60
MAX_MISSING_FRAC = 0.20
DETAIL_WITHIN_PCT = 0.15
FINANCIAL_SECTOR = "Financial Services"
DISCLAIMER = (
    "For research only — not investment advice. A few listed stocks may not be "
    "offered on Wealthsimple; confirm in the app."
)
