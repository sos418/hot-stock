#!/usr/bin/env python3
"""進入點:fetch → score → 寫每日快照 → 輸出 web/data.js。"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

import fetchers
import scoring

ROOT = Path(__file__).resolve().parent
# mock 模式使用獨立歷史目錄,避免覆蓋真實快照
HISTORY_DIR = ROOT / "data/history"
MOCK_HISTORY_DIR = ROOT / "data/mock_history"
DATA_JS = ROOT / "web/data.js"
CHAIN_CACHE = ROOT / "data/industry_chains.json"
CHART_SYMBOLS = ["^TWII", "^SOX", "^GSPC"]
MIN_GROUP_SIZE = 3  # 當日有成交成員數低於此值的族群不進熱度榜/評分
MAX_TOP_SHARE = 0.60  # 龍頭個股成交額占族群比重高於此值視為單股獨大,不進榜(非族群輪動)


def load_history(history_dir: Path) -> list:
    files = sorted(history_dir.glob("*.json"))
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def prior_highs_from_history(history: list, window: int = 20) -> dict:
    """過去至多 window 個交易日(不含今日)每檔收盤最高,供創新高判定。"""
    highs: dict = {}
    for day in history[-window:]:
        for s in day.get("stocks", []):
            c = s["code"]
            highs[c] = max(highs.get(c, 0.0), s["close"])
    return highs


def build_stocks(twse, tpex, capital, inst) -> pd.DataFrame:
    df = pd.concat([twse, tpex], ignore_index=True)
    df = df.merge(capital, on="code", how="left").merge(inst, on="code", how="left")
    df["inst_net_value"] = df["inst_net_shares"].fillna(0.0) * df["close"]
    df["market_cap"] = df["capital"].fillna(0.0) / 10.0 * df["close"]  # 面額10元近似
    return df


def fetch_with_fallback(history: list, refresh_industry: bool = False):
    """各來源獨立失敗處理:沿用最近快照之該部分,記入 stale 清單。"""
    stale = []
    last = history[-1] if history else None

    try:
        groups, chain_stale = fetchers.fetch_chain_groups(CHAIN_CACHE, force=refresh_industry)
        if chain_stale:
            stale.append("產業分類")
    except fetchers.FetchError as e:
        # 無快取又抓不到分類 → 無法分群,屬致命錯誤
        print(f"產業分類取得失敗且無本地快取,無法執行:{e}")
        sys.exit(1)

    try:
        twse = fetchers.fetch_twse_daily()
    except fetchers.FetchError as e:
        twse = None
        stale.append(e.source)
    try:
        tpex = fetchers.fetch_tpex_daily()
        if tpex.empty:
            raise fetchers.FetchError("上櫃行情", ValueError("empty"))
    except fetchers.FetchError as e:
        tpex = pd.DataFrame(columns=["code", "name", "close", "high", "change_pct", "turnover"])
        stale.append(e.source)
    try:
        capital = fetchers.fetch_capital_map()
    except fetchers.FetchError as e:
        capital = pd.DataFrame(columns=["code", "capital"])
        stale.append(e.source)
    try:
        inst = fetchers.fetch_institutional()
    except fetchers.FetchError as e:
        inst = pd.DataFrame(columns=["code", "inst_net_shares"])
        stale.append(e.source)

    indices, failed = fetchers.fetch_indices()
    if failed:
        if last:
            for sym in failed:
                snap = last.get("indices", {}).get(sym)
                if snap:
                    indices[sym] = pd.Series(snap["closes"], index=snap["dates"], dtype=float)
        stale.append("國際指數(" + ",".join(failed) + ")")
    return twse, tpex, capital, inst, groups, indices, stale


def render_indices(indices: dict) -> dict:
    cards = []
    for sym, name in fetchers.INDEX_SYMBOLS.items():
        if sym not in indices:
            cards.append({"symbol": sym, "name": name, "close": None,
                          "change_pct": None, "d5_pct": None, "d20_pct": None})
            continue
        cards.append({"symbol": sym, "name": name, **scoring.index_stats(indices[sym])})

    frame = pd.DataFrame({s: indices[s] for s in CHART_SYMBOLS if s in indices})
    frame = frame.sort_index().ffill().dropna()
    chart = {"labels": list(frame.index),
             "series": {s: scoring.normalize_base100(frame[s]) for s in frame.columns}}
    corr = None
    if "^TWII" in indices and "^SOX" in indices:
        corr = scoring.rolling_correlation(indices["^TWII"], indices["^SOX"], 20)
    return {"cards": cards, "chart": chart, "corr_twii_sox": corr}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="使用 data/mock/ 樣本離線執行")
    ap.add_argument("--refresh-industry", action="store_true",
                    help="強制更新產業價值鏈分類快取")
    ap.add_argument("--strong-threshold", type=float, default=scoring.STRONG_THRESHOLD,
                    help=f"F3 強勢股漲幅門檻%%(預設 {scoring.STRONG_THRESHOLD};儀表板可再動態調整)")
    args = ap.parse_args()
    if args.mock:
        fetchers.set_mock(ROOT / "data/mock")

    history_dir = MOCK_HISTORY_DIR if args.mock else HISTORY_DIR
    history_dir.mkdir(parents=True, exist_ok=True)
    history = load_history(history_dir)
    twse, tpex, capital, inst, groups, indices, stale = fetch_with_fallback(
        history, refresh_industry=args.refresh_industry)

    # 休市判定:上市行情空 或 資料日期非今日(mock 模式以資料日期為今日)
    if twse is None or twse.empty:
        print("今日休市/資料未更新(無上市行情資料)")
        sys.exit(0)
    data_date = twse.attrs.get("date")
    today = data_date if (args.mock and data_date) else dt.date.today()
    if data_date and data_date != today:
        print(f"今日休市/資料未更新(資料日期 {data_date})")
        sys.exit(0)
    date_str = today.strftime("%Y-%m-%d")

    stocks = build_stocks(twse, tpex, capital, inst)
    history = [h for h in history if h["date"] != date_str]  # 同日重跑覆蓋
    prior_highs = prior_highs_from_history(history)

    total_turnover = float(stocks["turnover"].sum())
    market_change = float((stocks["change_pct"].fillna(0) * stocks["turnover"]).sum()
                          / total_turnover) if total_turnover else 0.0

    # 一檔多族群:explode 成 (個股, 族群) 列;占比分母=全市場;小族群不排名
    member_rows = stocks.merge(groups.rename(columns={"group": "industry"}), on="code")
    sectors = scoring.aggregate_sectors(member_rows, prior_highs,
                                        market_turnover=total_turnover)
    sectors = sectors[(sectors["member_count"] >= MIN_GROUP_SIZE)
                      & (sectors["top_share"] <= MAX_TOP_SHARE)]

    snapshot = {
        "date": date_str,
        "market_change_pct": round(market_change, 4),
        # change_pct 供跨日趨勢(任一門檻的強勢股家數)回算;close 供創新高比對
        "stocks": [{"code": r.code, "close": r.close, "turnover": r.turnover,
                    "change_pct": round(float(r.change_pct), 2) if pd.notna(r.change_pct) else None}
                   for r in stocks.itertuples() if pd.notna(r.close)],
        "sectors": {idx: {k: (float(v) if pd.notna(v) else 0.0) for k, v in row.items()}
                    for idx, row in sectors.iterrows()},
        "indices": {sym: {"dates": list(s.index), "closes": [float(x) for x in s]}
                    for sym, s in indices.items()},
    }
    # F3 今日強勢族群:輸出每檔(個股,族群)的漲幅原始資料,門檻由前端動態計算
    # 每列 [代號, 名稱, 漲幅%, 所屬產業鏈, 族群名];前端依輸入門檻即時統計強勢股家數
    f3_members = [[r.code, r.name, round(float(r.change_pct), 2), r.chain, r.industry]
                  for r in member_rows.itertuples() if pd.notna(r.change_pct)]

    (history_dir / f"{date_str}.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")

    hot = [{"industry": idx,
            "avg_change_pct": round(float(r["avg_change_pct"]), 2),
            "turnover_share": round(float(r["turnover_share"]), 4),
            "limit_up_count": int(r["limit_up_count"]),
            "new_high_count": int(r["new_high_count"])}
           for idx, r in sectors.iterrows()]

    payload = {
        "date": date_str,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stale_sources": stale,
        "indices": render_indices(indices),
        "sectors_hot": hot,
        "f3_members": f3_members,
        "strong_threshold": args.strong_threshold,
        "min_group_size": MIN_GROUP_SIZE,
    }
    DATA_JS.parent.mkdir(parents=True, exist_ok=True)
    DATA_JS.write_text("window.DASHBOARD_DATA = "
                       + json.dumps(payload, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"完成:{date_str},族群 {len(hot)} 個,快照與 web/data.js 已更新"
          + (f";資料延遲:{','.join(stale)}" if stale else ""))


if __name__ == "__main__":
    main()
