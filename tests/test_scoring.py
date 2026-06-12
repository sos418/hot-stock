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
