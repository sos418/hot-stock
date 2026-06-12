from pathlib import Path

import fetchers

MOCK = Path(__file__).resolve().parents[1] / "data/mock"


def setup_module():
    fetchers.set_mock(MOCK)


def teardown_module():
    fetchers.set_mock(None)


def test_mock_daily_quotes():
    twse, tpex = fetchers.fetch_twse_daily(), fetchers.fetch_tpex_daily()
    assert len(twse) == 12 and len(tpex) == 4
    assert {"code", "close", "change_pct", "turnover"} <= set(twse.columns)
    assert twse.attrs["date"] is not None


def test_mock_industry_and_institutional():
    ind = fetchers.fetch_industry_map()
    assert len(ind) == 16
    assert "半導體業" in set(ind["industry"])
    inst = fetchers.fetch_institutional()
    assert len(inst) == 16


def test_mock_indices():
    series, failed = fetchers.fetch_indices()
    assert failed == [] and len(series) == 8
    assert len(series["^TWII"]) == 60
