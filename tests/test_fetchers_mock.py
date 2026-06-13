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


def test_mock_capital_and_institutional():
    cap = fetchers.fetch_capital_map()
    assert len(cap) == 16
    assert {"code", "capital"} <= set(cap.columns)
    assert (cap["capital"] > 0).all()
    inst = fetchers.fetch_institutional()
    assert len(inst) == 16


def test_mock_chain_groups():
    df, stale = fetchers.fetch_chain_groups(Path("/tmp/nonexistent_cache.json"))
    assert stale is False
    assert {"code", "group", "level"} <= set(df.columns)
    assert (df["group"] == "晶圓製造").sum() >= 3
    assert df.loc[df["group"] == "晶圓製造", "level"].iloc[0] == "sub"
    assert df.loc[df["group"] == "半導體", "level"].iloc[0] == "chain"


def test_mock_indices():
    series, failed = fetchers.fetch_indices()
    assert failed == [] and len(series) == 8
    assert len(series["^TWII"]) == 60
