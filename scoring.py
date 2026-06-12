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
