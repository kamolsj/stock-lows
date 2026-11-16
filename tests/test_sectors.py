from stocklows.sectors import sector_check


def test_sector_down_too():
    r = sector_check(-0.30, [-0.2] * 6)
    assert r["verdict"] == "sector" and r["sector_median_pct"] == -0.2 and r["stock_pct"] == -0.30


def test_stock_specific():
    assert sector_check(-0.30, [0.05] * 6)["verdict"] == "stock"


def test_boundary_minus_ten():
    assert sector_check(-0.30, [-0.10] * 5)["verdict"] == "sector"


def test_too_few_peers():
    r = sector_check(-0.30, [-0.2] * 4)
    assert r["verdict"] == "unknown" and r["sector_median_pct"] is None
