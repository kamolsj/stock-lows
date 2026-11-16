from stocklows import config


def test_periods():
    assert config.PERIODS == {"1Y": 365, "5Y": 1826, "10Y": 3652, "20Y": 7305}
    assert config.NEAR_PCT == 0.05
