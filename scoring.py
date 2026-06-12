"""族群熱度與突破口評分。純函式,不做任何網路存取。"""
from __future__ import annotations

import numpy as np
import pandas as pd

LIMIT_UP_THRESHOLD = 9.8  # 台股漲停 10%,留浮點容差

WEIGHTS = {
    "vol_slope": 20.0, "high_delta": 20.0,
    "inst_strength": 15.0, "inst_streak": 15.0,
    "low_base": 15.0, "rs_turn": 15.0,
}


def percentile_rank(values: pd.Series) -> pd.Series:
    """全族群分位數正規化至 [0,1];元素少於 2 時回傳 0.5。"""
    n = len(values)
    if n <= 1:
        return pd.Series(0.5, index=values.index)
    r = values.rank(method="average")
    return (r - 1) / (n - 1)


def slope(values) -> float:
    """最小平方法斜率;少於 2 點回傳 0。"""
    vals = [v for v in values if v is not None and not pd.isna(v)]
    if len(vals) < 2:
        return 0.0
    x = np.arange(len(vals), dtype=float)
    return float(np.polyfit(x, np.array(vals, dtype=float), 1)[0])


def index_stats(closes: pd.Series) -> dict:
    """近N日收盤序列(舊→新)→ 收盤/漲跌%/5日%/20日%。資料不足的欄位為 None。"""
    closes = closes.dropna()

    def pct(n: int):
        if len(closes) <= n:
            return None
        return round((closes.iloc[-1] / closes.iloc[-1 - n] - 1) * 100, 2)

    return {"close": round(float(closes.iloc[-1]), 2),
            "change_pct": pct(1), "d5_pct": pct(5), "d20_pct": pct(20)}


def normalize_base100(closes: pd.Series) -> list:
    """標準化走勢,基期=100。"""
    closes = closes.dropna()
    if closes.empty:
        return []
    return [round(float(c) / float(closes.iloc[0]) * 100, 2) for c in closes]


def rolling_correlation(a: pd.Series, b: pd.Series, window: int = 20):
    """兩收盤序列之日報酬 window 日相關係數;樣本不足回傳 None。"""
    ra, rb = a.pct_change(), b.pct_change()
    joined = pd.concat([ra, rb], axis=1, join="inner").dropna()
    if len(joined) < window:
        return None
    tail = joined.tail(window)
    return round(float(tail.iloc[:, 0].corr(tail.iloc[:, 1])), 2)
