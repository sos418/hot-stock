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


def aggregate_sectors(stocks: pd.DataFrame, prior_highs: dict,
                      market_turnover: float | None = None) -> pd.DataFrame:
    """個股 → 族群彙總(F2)。

    stocks 欄位: code,name,industry,close,change_pct,turnover,inst_net_value,market_cap
    (一檔多族群時,以多列(個股,族群)輸入)
    prior_highs: 每檔過去(至多20日,不含今日)收盤最高;不在表內者不計新高。
    market_turnover: 成交占比分母(全市場成交金額);未提供時退回族群加總。
    """
    df = stocks.dropna(subset=["industry", "close", "turnover"]).copy()
    df["change_pct"] = df["change_pct"].fillna(0.0)
    df["inst_net_value"] = df["inst_net_value"].fillna(0.0)
    df["is_limit_up"] = df["change_pct"] >= LIMIT_UP_THRESHOLD
    df["is_new_high"] = [
        c in prior_highs and close > prior_highs[c]
        for c, close in zip(df["code"], df["close"])
    ]
    df["w_change"] = df["change_pct"] * df["turnover"]
    g = df.groupby("industry")
    turnover = g["turnover"].sum()
    out = pd.DataFrame({
        "turnover": turnover,
        "avg_change_pct": (g["w_change"].sum() / turnover.replace(0, np.nan)).fillna(0.0),
        "limit_up_count": g["is_limit_up"].sum().astype(int),
        "new_high_count": g["is_new_high"].sum().astype(int),
        "inst_net_value": g["inst_net_value"].sum(),
        "market_cap": g["market_cap"].sum(),
        "member_count": g["code"].nunique().astype(int),
    })
    total = float(market_turnover) if market_turnover else float(out["turnover"].sum())
    out["turnover_share"] = out["turnover"] / total if total else 0.0
    return out.sort_values("turnover", ascending=False)


def rolling_correlation(a: pd.Series, b: pd.Series, window: int = 20):
    """兩收盤序列之日報酬 window 日相關係數;樣本不足回傳 None。"""
    ra, rb = a.pct_change(), b.pct_change()
    joined = pd.concat([ra, rb], axis=1, join="inner").dropna()
    if len(joined) < window:
        return None
    tail = joined.tail(window)
    return round(float(tail.iloc[:, 0].corr(tail.iloc[:, 1])), 2)


def _series(history: list, industry: str, field: str) -> list:
    return [d["sectors"][industry][field] for d in history if industry in d["sectors"]]


def _compound(changes: list) -> float:
    """漲跌% 序列 → 區間累積報酬%。"""
    r = 1.0
    for c in changes:
        r *= 1 + c / 100.0
    return (r - 1) * 100


def compute_breakout_scores(history: list) -> pd.DataFrame:
    """突破口綜合評分(F3)。history: 每日快照(舊→新,今日為最後一筆)。

    回傳 index=族群,columns=[vol_slope, high_delta, inst_strength,
    inst_streak, ret20, rs_turn, score],score 介於 0–100。
    """
    today = history[-1]
    columns = ["vol_slope", "high_delta", "inst_strength", "inst_streak",
               "ret20", "rs_turn", "score"]
    if not today["sectors"]:
        return pd.DataFrame(columns=columns)
    rows = {}
    for s in today["sectors"]:
        share5 = _series(history[-5:], s, "turnover_share")
        highs = _series(history, s, "new_high_count")
        high_delta = highs[-1] - (highs[-4] if len(highs) >= 4 else highs[0])
        inst3 = sum(_series(history[-3:], s, "inst_net_value"))
        cap = today["sectors"][s].get("market_cap") or 0.0
        streak = 0
        for v in reversed(_series(history, s, "inst_net_value")):
            if v > 0:
                streak += 1
            else:
                break
        ch = _series(history[-21:], s, "avg_change_pct")
        mch = [d["market_change_pct"] for d in history[-21:]]
        rs5_now = _compound(ch[-5:]) - _compound(mch[-5:])
        rs5_prev = (_compound(ch[-6:-1]) - _compound(mch[-6:-1])) if len(ch) >= 6 else None
        rows[s] = {
            "vol_slope": slope(share5),
            "high_delta": float(high_delta),
            "inst_strength": inst3 / cap if cap > 0 else 0.0,
            "inst_streak": float(streak),
            "ret20": _compound(ch),
            "rs_turn": 1.0 if (rs5_prev is not None and rs5_prev <= 0 < rs5_now) else 0.0,
        }
    df = pd.DataFrame.from_dict(rows, orient="index")
    score = (
        WEIGHTS["vol_slope"] * percentile_rank(df["vol_slope"])
        + WEIGHTS["high_delta"] * percentile_rank(df["high_delta"])
        + WEIGHTS["inst_strength"] * percentile_rank(df["inst_strength"])
        + WEIGHTS["inst_streak"] * percentile_rank(df["inst_streak"])
        + WEIGHTS["low_base"] * percentile_rank(-df["ret20"]) * (percentile_rank(df["ret20"]) <= 0.5)
        + WEIGHTS["rs_turn"] * df["rs_turn"]
    )
    df["score"] = score.round(1)
    return df.sort_values("score", ascending=False)


def score_arrow(scores: list) -> str:
    """近3日評分(舊→新,含今日)→ ↑(連升)/↓(連跌)/→;不足3日回「資料累積中」。"""
    if len(scores) < 3:
        return "資料累積中"
    a, b, c = scores[-3:]
    if a < b < c:
        return "↑"
    if a > b > c:
        return "↓"
    return "→"
