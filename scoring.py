"""族群熱度與突破口評分。純函式,不做任何網路存取。"""
from __future__ import annotations

import numpy as np
import pandas as pd

LIMIT_UP_THRESHOLD = 9.8  # 台股漲停 10%,留浮點容差
STRONG_THRESHOLD = 8.0    # 當日漲幅 > 此值視為強勢股(漲停10%,>8%=準漲停)


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
        # 龍頭個股成交額占該族群比重(集中度);族群內每檔唯一一列,取組內最大
        "top_share": (g["turnover"].max() / turnover.replace(0, np.nan)).fillna(0.0),
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


# F3「今日強勢族群」的統計(依輸入門檻計強勢股家數、族群成員數、強勢比例,
# 以產業鏈為大傘、子群為層級)改在前端 web/dashboard.html 動態計算,
# 以支援使用者即時調整漲幅門檻;此處僅保留 STRONG_THRESHOLD 作為預設值。
