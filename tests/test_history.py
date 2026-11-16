from datetime import date

import pandas as pd

from stocklows.history import HistoryStore


def bars(dates, low, splits=None):
    idx = pd.DatetimeIndex(pd.to_datetime(dates))
    n = len(idx)
    return pd.DataFrame({"Open": low, "High": low, "Low": [low] * n, "Close": [low] * n,
                         "Volume": [1000.0] * n, "Splits": splits or [0.0] * n}, index=idx)


class FakeDownloader:
    def __init__(self, responses):
        self.responses = responses  # list of dicts returned in order
        self.calls = []

    def __call__(self, symbols, start=None, period=None):
        self.calls.append({"symbols": list(symbols), "start": start, "period": period})
        resp = self.responses.pop(0)
        return {s: df for s, df in resp.items() if s in symbols}


def test_new_symbol_full_download(tmp_path):
    dl = FakeDownloader([{"AAA": bars(["2026-11-12", "2026-11-13"], 10.0)}])
    store = HistoryStore(tmp_path)
    out = store.update(["AAA"], date(2026, 11, 16), downloader=dl)
    assert dl.calls[0]["period"] == "max"
    assert len(out["AAA"]) == 2


def test_append_only_new_dates(tmp_path):
    dl = FakeDownloader([
        {"AAA": bars(["2026-11-12", "2026-11-13"], 10.0)},
        {"AAA": bars(["2026-11-13", "2026-11-16"], 11.0)},
    ])
    store = HistoryStore(tmp_path)
    store.update(["AAA"], date(2026, 11, 13), downloader=dl)
    out = store.update(["AAA"], date(2026, 11, 16), downloader=dl)
    assert dl.calls[1]["start"] == date(2026, 11, 13)
    assert list(out["AAA"].index.strftime("%Y-%m-%d")) == ["2026-11-12", "2026-11-13", "2026-11-16"]
    assert out["AAA"].index.is_unique
    assert out["AAA"].loc["2026-11-16", "Low"] == 11.0


def test_split_triggers_full_redownload(tmp_path):
    dl = FakeDownloader([
        {"AAA": bars(["2026-11-12", "2026-11-13"], 100.0)},
        {"AAA": bars(["2026-11-16"], 50.0, splits=[2.0])},
        {"AAA": bars(["2026-11-12", "2026-11-13", "2026-11-16"], 50.0)},  # adjusted
    ])
    store = HistoryStore(tmp_path)
    store.update(["AAA"], date(2026, 11, 13), downloader=dl)
    out = store.update(["AAA"], date(2026, 11, 16), downloader=dl)
    assert dl.calls[2]["period"] == "max" and dl.calls[2]["symbols"] == ["AAA"]
    assert (out["AAA"]["Low"] == 50.0).all()


def test_symbol_missing_from_download_keeps_old(tmp_path):
    dl = FakeDownloader([{"AAA": bars(["2026-11-13"], 10.0)}, {}])
    store = HistoryStore(tmp_path)
    store.update(["AAA"], date(2026, 11, 13), downloader=dl)
    out = store.update(["AAA"], date(2026, 11, 16), downloader=dl)
    assert len(out["AAA"]) == 1


def test_roundtrip_save_load(tmp_path):
    dl = FakeDownloader([{"AAA": bars(["2026-11-12", "2026-11-13"], 10.0),
                          "BBB.TO": bars(["2026-11-13"], 5.0)}])
    store = HistoryStore(tmp_path)
    store.update(["AAA", "BBB.TO"], date(2026, 11, 16), downloader=dl)
    store.save()
    loaded = HistoryStore(tmp_path).load()
    assert set(loaded) == {"AAA", "BBB.TO"}
    assert list(loaded["AAA"].columns) == ["Low", "Close", "Volume"]
    assert loaded["BBB.TO"].iloc[0]["Close"] == 5.0


def test_late_split_on_overlap_row_triggers_full_redownload(tmp_path):
    dl = FakeDownloader([
        {"AAA": bars(["2026-11-12", "2026-11-13"], 100.0)},
        {"AAA": bars(["2026-11-13", "2026-11-16"], 50.0)},   # overlap row re-adjusted, no split flag
        {"AAA": bars(["2026-11-12", "2026-11-13", "2026-11-16"], 50.0)},
    ])
    store = HistoryStore(tmp_path)
    store.update(["AAA"], date(2026, 11, 13), downloader=dl)
    out = store.update(["AAA"], date(2026, 11, 16), downloader=dl)
    assert dl.calls[2]["period"] == "max"
    assert (out["AAA"]["Low"] == 50.0).all()


def test_normal_move_on_overlap_row_is_not_a_split(tmp_path):
    dl = FakeDownloader([
        {"AAA": bars(["2026-11-13"], 100.0)},
        {"AAA": bars(["2026-11-13", "2026-11-16"], 104.0)},
    ])
    store = HistoryStore(tmp_path)
    store.update(["AAA"], date(2026, 11, 13), downloader=dl)
    store.update(["AAA"], date(2026, 11, 16), downloader=dl)
    assert len(dl.calls) == 2
