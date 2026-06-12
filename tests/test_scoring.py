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


def test_aggregate_sectors():
    stocks = pd.DataFrame([
        {"code": "2330", "name": "台積電", "industry": "半導體業", "close": 1000.0,
         "change_pct": 10.0, "turnover": 3000.0, "inst_net_value": 500.0, "market_cap": 10000.0},
        {"code": "2303", "name": "聯電", "industry": "半導體業", "close": 50.0,
         "change_pct": -2.0, "turnover": 1000.0, "inst_net_value": -100.0, "market_cap": 2000.0},
        {"code": "2882", "name": "國泰金", "industry": "金融保險", "close": 60.0,
         "change_pct": 1.0, "turnover": 1000.0, "inst_net_value": 0.0, "market_cap": 5000.0},
    ])
    prior_highs = {"2330": 900.0, "2303": 60.0}  # 國泰金無歷史 → 不計新高
    out = scoring.aggregate_sectors(stocks, prior_highs)
    semi = out.loc["半導體業"]
    assert semi["turnover"] == 4000.0
    assert semi["avg_change_pct"] == pytest.approx(7.0)  # 成交金額加權
    assert semi["limit_up_count"] == 1
    assert semi["new_high_count"] == 1
    assert semi["inst_net_value"] == 400.0
    assert out.loc["金融保險", "turnover_share"] == pytest.approx(0.2)


def _day(date, strong, weak):
    return {"date": date, "market_change_pct": 0.0, "sectors": {"強": strong, "弱": weak}}


def make_history():
    """強: 量價籌碼全面領先、20日低基期、5日相對強度由負轉正 → 100分。
    弱: 全面落後、漲幅在前50% → 0分。"""
    strong_chg = [-5.0, -5.0, 0.0, 0.0, 0.0, 1.0, 1.0]
    weak_chg = [1.0] * 7
    hist = []
    for i in range(7):
        hist.append(_day(
            f"2026-06-0{i + 1}",
            {"turnover_share": 0.1 + 0.03 * i, "avg_change_pct": strong_chg[i],
             "new_high_count": i, "inst_net_value": 100.0, "market_cap": 1000.0},
            {"turnover_share": 0.3 - 0.03 * i, "avg_change_pct": weak_chg[i],
             "new_high_count": 6 - i, "inst_net_value": -100.0, "market_cap": 1000.0},
        ))
    return hist


def test_breakout_score_boundaries():
    df = scoring.compute_breakout_scores(make_history())
    assert df.loc["強", "score"] == 100.0
    assert df.loc["弱", "score"] == 0.0


def test_score_arrow():
    assert scoring.score_arrow([10.0, 20.0]) == "資料累積中"
    assert scoring.score_arrow([10.0, 20.0, 30.0]) == "↑"
    assert scoring.score_arrow([30.0, 20.0, 10.0]) == "↓"
    assert scoring.score_arrow([10.0, 30.0, 20.0]) == "→"
    assert scoring.score_arrow([10.0, 10.0, 20.0]) == "→"  # 非連升不給↑


def test_breakout_scores_empty_sectors():
    """族群為空(如產業別來源失敗)時應回傳空結果而非拋例外。"""
    df = scoring.compute_breakout_scores([{"date": "2026-06-12", "market_change_pct": 0.0, "sectors": {}}])
    assert df.empty
    assert "score" in df.columns
