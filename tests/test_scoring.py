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


def test_aggregate_sectors_up_ratio_and_ex():
    """up_ratio=上漲家數比例(廣度);turnover_share_ex=排除權王後占比。"""
    rows = [
        {"code": "A", "industry": "G1", "turnover": 600.0, "change_pct": 5.0},   # 權王、上漲
        {"code": "B", "industry": "G1", "turnover": 200.0, "change_pct": -1.0},  # 下跌
        {"code": "A", "industry": "G2", "turnover": 600.0, "change_pct": 5.0},
        {"code": "C", "industry": "G2", "turnover": 200.0, "change_pct": 3.0},   # 上漲
    ]
    for r in rows:
        r.update(name=r["code"], close=10.0, inst_net_value=0.0, market_cap=100.0)
    out = scoring.aggregate_sectors(pd.DataFrame(rows), {}, market_turnover=1400.0,
                                    exclude_code="A", market_turnover_ex=400.0)
    assert out.loc["G1", "up_ratio"] == pytest.approx(0.5)   # A漲 B跌
    assert out.loc["G2", "up_ratio"] == pytest.approx(1.0)   # A、C 皆漲
    assert out.loc["G1", "turnover_share_ex"] == pytest.approx(0.5)  # 排除A:B200/400
    assert out.loc["G2", "turnover_share_ex"] == pytest.approx(0.5)  # 排除A:C200/400


def test_build_trends():
    days = [
        {"date": "2026-06-11", "stocks": [
            {"code": "A", "change_pct": 9.0, "turnover": 50.0},   # 權王、強勢
            {"code": "B", "change_pct": 1.0, "turnover": 10.0},
            {"code": "Z", "change_pct": 0.0, "turnover": 40.0}]},  # 鏈外
        {"date": "2026-06-12", "stocks": [
            {"code": "A", "change_pct": 9.0, "turnover": 50.0},
            {"code": "B", "change_pct": 9.5, "turnover": 30.0},
            {"code": "Z", "change_pct": 0.0, "turnover": 20.0}]},
    ]
    cm = {"半導體": {"A", "B", "C"}}  # C 當天無成交 → 不計
    t = scoring.build_trends(days, cm, threshold=8.0)
    assert t["dates"] == ["2026-06-11", "2026-06-12"]
    assert t["chains"]["半導體"]["strong_count"] == [1, 2]
    # 含權王:(A+B)/total → d1 60/100, d2 80/100
    assert t["chains"]["半導體"]["turnover_share"] == [60.0, 80.0]
    # 排除權王 A:B/(total-A) → d1 10/50=20%, d2 30/50=60%
    assert t["chains"]["半導體"]["turnover_share_ex"] == [20.0, 60.0]


def test_build_trends_ex_single_stock_is_none():
    """全市場僅一檔(它就是權王)→ 排除後分母 0,turnover_share_ex 為 None。"""
    days = [{"date": "d1", "stocks": [{"code": "A", "change_pct": 9.0, "turnover": 10.0}]}]
    t = scoring.build_trends(days, {"X": {"A"}}, threshold=8.0)
    assert t["chains"]["X"]["strong_count"] == [1]
    assert t["chains"]["X"]["turnover_share"] == [100.0]
    assert t["chains"]["X"]["turnover_share_ex"] == [None]
