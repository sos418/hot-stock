import pandas as pd
import pytest

import scoring


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


def test_strong_stock_sectors():
    """強勢股(漲幅>8%)族群榜:依家數排序,家數<2 與門檻邊界排除。"""
    data = [
        ("X", "G0", 9.0), ("Y", "G0", 9.0), ("Z", "G0", 9.0),  # G0: 3 強勢
        ("A", "G1", 9.0), ("B", "G1", 10.0), ("C", "G1", 1.0),  # G1: 2 強勢 / 3
        ("D", "G2", 9.5), ("E", "G2", 2.0),                      # G2: 1 強勢 → 不入榜
        ("F", "G3", 8.0),                                        # 8.0 非 >8 → 0 強勢
    ]
    rows = [{"code": c, "name": c, "industry": g, "change_pct": p} for c, g, p in data]
    out = scoring.strong_stock_sectors(pd.DataFrame(rows))
    assert list(out.index) == ["G0", "G1"]          # 依家數排序、<2 已濾
    assert out.loc["G1", "strong_count"] == 2
    assert out.loc["G1", "member_count"] == 3
    assert out.loc["G1", "strong_ratio"] == pytest.approx(2 / 3)


def test_strong_stock_sectors_empty():
    out = scoring.strong_stock_sectors(pd.DataFrame(columns=["code", "industry", "change_pct"]))
    assert out.empty
    assert "strong_count" in out.columns


def test_aggregate_sectors_market_denominator_and_member_count():
    rows = []
    for code, grp, turnover in [("A", "G1", 600.0), ("B", "G1", 200.0),
                                ("A", "G2", 600.0), ("C", "G2", 200.0)]:
        rows.append({"code": code, "name": code, "industry": grp, "close": 10.0,
                     "change_pct": 1.0, "turnover": turnover,
                     "inst_net_value": 0.0, "market_cap": 100.0})
    out = scoring.aggregate_sectors(pd.DataFrame(rows), {}, market_turnover=1000.0)
    assert out.loc["G1", "turnover_share"] == pytest.approx(0.8)  # 分母=全市場
    assert out.loc["G1", "member_count"] == 2


def test_aggregate_sectors_top_share():
    """top_share = 龍頭個股成交額占該族群比重,供集中度過濾。"""
    rows = []
    for code, grp, turnover in [("A", "G1", 800.0), ("B", "G1", 200.0),   # 龍頭 80%
                                ("C", "G2", 500.0), ("D", "G2", 500.0)]:  # 各 50%
        rows.append({"code": code, "name": code, "industry": grp, "close": 10.0,
                     "change_pct": 1.0, "turnover": turnover,
                     "inst_net_value": 0.0, "market_cap": 100.0})
    out = scoring.aggregate_sectors(pd.DataFrame(rows), {})
    assert out.loc["G1", "top_share"] == pytest.approx(0.8)
    assert out.loc["G2", "top_share"] == pytest.approx(0.5)
