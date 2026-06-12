import pandas as pd
import pytest

import scoring


def test_percentile_rank_normalizes_to_unit_interval():
    s = pd.Series([10, 20, 30, 40], index=list("abcd"))
    r = scoring.percentile_rank(s)
    assert r["a"] == 0.0
    assert r["d"] == 1.0
    assert r["b"] == pytest.approx(1 / 3)


def test_percentile_rank_ties_and_singleton():
    assert scoring.percentile_rank(pd.Series([5, 5], index=["a", "b"])).tolist() == [0.5, 0.5]
    assert scoring.percentile_rank(pd.Series([7], index=["x"])).iloc[0] == 0.5


def test_slope():
    assert scoring.slope([1, 2, 3, 4, 5]) == pytest.approx(1.0)
    assert scoring.slope([3]) == 0.0
    assert scoring.slope([]) == 0.0


def test_index_stats():
    closes = pd.Series([float(100 + i) for i in range(25)])  # 100..124
    s = scoring.index_stats(closes)
    assert s["close"] == 124.0
    assert s["change_pct"] == pytest.approx((124 / 123 - 1) * 100, abs=0.01)
    assert s["d5_pct"] == pytest.approx((124 / 119 - 1) * 100, abs=0.01)
    assert s["d20_pct"] == pytest.approx((124 / 104 - 1) * 100, abs=0.01)


def test_normalize_base100():
    out = scoring.normalize_base100(pd.Series([50.0, 55.0, 60.0]))
    assert out == [100.0, 110.0, 120.0]


def test_rolling_correlation_perfect():
    a = pd.Series([float(i) for i in range(1, 31)])
    assert scoring.rolling_correlation(a, a * 2, window=20) == pytest.approx(1.0)
    assert scoring.rolling_correlation(a.head(5), a.head(5)) is None  # 不足20日
