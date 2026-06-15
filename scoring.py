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
                      market_turnover: float | None = None,
                      exclude_code: str | None = None,
                      market_turnover_ex: float | None = None) -> pd.DataFrame:
    """個股 → 族群彙總(F2)。

    stocks 欄位: code,name,industry,close,change_pct,turnover,inst_net_value,market_cap
    (一檔多族群時,以多列(個股,族群)輸入)
    prior_highs: 每檔過去(至多20日,不含今日)收盤最高;不在表內者不計新高。
    market_turnover: 成交占比分母(全市場成交金額);未提供時退回族群加總。
    exclude_code/market_turnover_ex: 排除權王(如台積電)後的成交占比;
      turnover_share_ex = 該族群扣除 exclude_code 之成交額 / market_turnover_ex。
    回傳含 up_ratio(成員上漲家數比例,廣度)、turnover_share / turnover_share_ex。
    """
    df = stocks.dropna(subset=["industry", "close", "turnover"]).copy()
    df["change_pct"] = df["change_pct"].fillna(0.0)
    df["inst_net_value"] = df["inst_net_value"].fillna(0.0)
    df["is_limit_up"] = df["change_pct"] >= LIMIT_UP_THRESHOLD
    df["is_up"] = df["change_pct"] > 0
    df["is_new_high"] = [
        c in prior_highs and close > prior_highs[c]
        for c, close in zip(df["code"], df["close"])
    ]
    df["w_change"] = df["change_pct"] * df["turnover"]
    df["turnover_ex"] = df["turnover"].where(df["code"] != exclude_code, 0.0)
    g = df.groupby("industry")
    turnover = g["turnover"].sum()
    out = pd.DataFrame({
        "turnover": turnover,
        "avg_change_pct": (g["w_change"].sum() / turnover.replace(0, np.nan)).fillna(0.0),
        "up_ratio": g["is_up"].mean(),  # 成員上漲家數比例(等權廣度)
        "limit_up_count": g["is_limit_up"].sum().astype(int),
        "new_high_count": g["is_new_high"].sum().astype(int),
        "inst_net_value": g["inst_net_value"].sum(),
        "market_cap": g["market_cap"].sum(),
        "member_count": g["code"].nunique().astype(int),
        # 龍頭個股成交額占該族群比重(集中度);族群內每檔唯一一列,取組內最大
        "top_share": (g["turnover"].max() / turnover.replace(0, np.nan)).fillna(0.0),
        "turnover_ex": g["turnover_ex"].sum(),
    })
    total = float(market_turnover) if market_turnover else float(out["turnover"].sum())
    out["turnover_share"] = out["turnover"] / total if total else 0.0
    total_ex = float(market_turnover_ex) if market_turnover_ex else float(out["turnover_ex"].sum())
    out["turnover_share_ex"] = out["turnover_ex"] / total_ex if total_ex else 0.0
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


def build_trends(days: list, chain_members: dict,
                 threshold: float = STRONG_THRESHOLD) -> dict:
    """跨日趨勢(Phase 2):各產業鏈近 N 個交易日的強勢股家數與成交占比。

    days: 每日快照(舊→新),每筆需有 date、stocks([{code, change_pct, turnover}])。
    chain_members: {產業鏈: set(成員代號)}(取自分類的鏈層級)。
    threshold: 強勢股漲幅門檻(固定參考值,趨勢圖用)。
    回傳 {dates, chains:{鏈:{strong_count, turnover_share, turnover_share_ex}}};
    turnover_share 以 % 表示。turnover_share_ex 為「排除當日成交額最大個股
    (權王,通常台積電)」後的占比——降低台積電對台股結構性主導。
    """
    dates = [d["date"] for d in days]
    # 預先算每天:個股漲幅、個股成交額、全市場成交額、權王(成交最大)代號與其成交額
    cp_by_day, tn_by_day, total_by_day, totalex_by_day, top_by_day = [], [], [], [], []
    for d in days:
        cp, tn = {}, {}
        for s in d.get("stocks", []):
            cp[s["code"]] = s.get("change_pct")
            tn[s["code"]] = s.get("turnover") or 0.0
        total = sum(tn.values())
        top = max(tn, key=tn.get) if tn else None
        cp_by_day.append(cp)
        tn_by_day.append(tn)
        total_by_day.append(total)
        top_by_day.append(top)
        totalex_by_day.append(total - (tn.get(top, 0.0) if top else 0.0))

    def pct(num, den):
        return round(num / den * 100, 2) if den else None

    chains = {}
    for chain, members in chain_members.items():
        strong, share, share_ex = [], [], []
        for i in range(len(days)):
            cp, tn, top = cp_by_day[i], tn_by_day[i], top_by_day[i]
            strong.append(sum(1 for c in members
                              if cp.get(c) is not None and cp[c] > threshold))
            sec = sum(tn.get(c, 0.0) for c in members)
            sec_ex = sum(tn.get(c, 0.0) for c in members if c != top)
            share.append(pct(sec, total_by_day[i]))
            share_ex.append(pct(sec_ex, totalex_by_day[i]))
        chains[chain] = {"strong_count": strong,
                         "turnover_share": share, "turnover_share_ex": share_ex}
    return {"dates": dates, "chains": chains}
