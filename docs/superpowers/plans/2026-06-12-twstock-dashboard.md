# 台股分析儀表板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 `doc/2026-06-11-twstock-dashboard-design.md`,建出盤後執行一次、產出本機網頁儀表板的工具(國際大盤、熱門族群、突破口評分)。

**Architecture:** `fetchers.py` 抓取外部資料並正規化為 DataFrame;`scoring.py` 為純函式評分(零網路);`run.py` 串接、寫每日快照 `data/history/YYYY-MM-DD.json` 並輸出 `web/data.js`;`web/dashboard.html` 單檔前端(Chart.js CDN)。20日新高、法人連買、5日斜率等跨日指標一律由歷史快照計算,因此快照需保存個股收盤與族群彙總原始值。

**Tech Stack:** Python 3 + pandas + requests + yfinance + pytest;前端 vanilla JS + Chart.js 4 (CDN)。

**關鍵設計決策**(規格未明定處):
- 分位數正規化採 `(rank-1)/(n-1)` → 落在 [0,1],使滿分100/零分0邊界可達;單一元素回傳 0.5。
- 低基期(15分):`15 × percentile_rank(-ret20) × (ret20 位於後50%)`;相對強度轉正(15分)為二元:`rs5_prev ≤ 0 < rs5_now`。
- 創20日新高 = 今收盤 > 過去快照(至多20日)收盤最高;歷史不足時以現有天數計。
- 類股總市值 ≈ Σ(實收資本額/10 × 收盤價)(面額10元近似)。
- 法人買超金額 ≈ 買賣超股數 × 收盤價(免費端點無金額)。
- TWSE/TPEx OpenAPI 欄位名稱以候選清單容錯解析(`_pick`),mock 樣本鎖定一組欄位確保流程可測。

---

### Task 1: 專案腳手架

**Files:**
- Create: `requirements.txt`, `.gitignore`, `tests/conftest.py`

- [ ] **Step 1: git init 與目錄**

```bash
cd /Users/hgh/Projects/hot-stock
git init
mkdir -p data/history data/mock web tests scripts docs/superpowers/plans
```

- [ ] **Step 2: requirements.txt**

```
pandas>=2.0
requests>=2.31
yfinance>=0.2.40
pytest>=8.0
```

- [ ] **Step 3: .gitignore**

```
.venv/
__pycache__/
*.pyc
.DS_Store
data/history/
web/data.js
.pytest_cache/
```

- [ ] **Step 4: venv 與安裝**

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

- [ ] **Step 5: tests/conftest.py**(讓 tests 可 import 根目錄模組)

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

- [ ] **Step 6: Commit** `chore: 專案腳手架`

### Task 2: scoring — 分位數正規化與斜率

**Files:** Create `scoring.py`, `tests/test_scoring.py`

- [ ] **Step 1: 失敗測試**

```python
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
```

- [ ] **Step 2: 跑測試確認失敗** `.venv/bin/pytest tests/ -v` → ModuleNotFoundError/AttributeError
- [ ] **Step 3: 實作**

```python
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
```

- [ ] **Step 4: 跑測試通過**
- [ ] **Step 5: Commit** `feat: scoring 分位數正規化與斜率`

### Task 3: scoring — 指數統計(F1)

**Files:** Modify `scoring.py`, `tests/test_scoring.py`

- [ ] **Step 1: 失敗測試**

```python
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
```

- [ ] **Step 2: 確認失敗 → 實作**

```python
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
```

- [ ] **Step 3: 跑測試通過 → Commit** `feat: scoring 指數統計`

### Task 4: scoring — 族群彙總(F2)

**Files:** Modify `scoring.py`, `tests/test_scoring.py`

- [ ] **Step 1: 失敗測試**

```python
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
```

- [ ] **Step 2: 確認失敗 → 實作**

```python
def aggregate_sectors(stocks: pd.DataFrame, prior_highs: dict) -> pd.DataFrame:
    """個股 → 族群彙總(F2)。
    stocks 欄位: code,name,industry,close,change_pct,turnover,inst_net_value,market_cap
    prior_highs: 每檔過去(至多20日,不含今日)收盤最高;不在表內者不計新高。
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
    })
    total = float(out["turnover"].sum())
    out["turnover_share"] = out["turnover"] / total if total else 0.0
    return out.sort_values("turnover", ascending=False)
```

- [ ] **Step 3: 跑測試通過 → Commit** `feat: scoring 族群彙總`

### Task 5: scoring — 突破口評分與3日箭頭(F3)

**Files:** Modify `scoring.py`, `tests/test_scoring.py`

歷史快照(由 run.py 寫入)在 scoring 端的型別:`list[dict]`(舊→新,今日為最後一筆),每筆:
`{"date": str, "market_change_pct": float, "sectors": {族群: {turnover_share, avg_change_pct, new_high_count, inst_net_value, market_cap, ...}}}`

- [ ] **Step 1: 失敗測試**(滿分/零分邊界 + 箭頭)

```python
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
```

- [ ] **Step 2: 確認失敗 → 實作**

```python
def _series(history: list, industry: str, field: str) -> list:
    return [d["sectors"][industry][field] for d in history if industry in d["sectors"]]


def _compound(changes: list) -> float:
    """漲跌% 序列 → 區間累積報酬%。"""
    r = 1.0
    for c in changes:
        r *= 1 + c / 100.0
    return (r - 1) * 100


def compute_breakout_scores(history: list) -> pd.DataFrame:
    """history: 每日快照(舊→新,今日為最後一筆)。回傳 index=族群,
    columns=[vol_slope, high_delta, inst_strength, inst_streak, ret20, rs_turn, score]。"""
    today = history[-1]
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
```

- [ ] **Step 3: 跑全部測試通過 → Commit** `feat: scoring 突破口評分與箭頭`

### Task 6: fetchers.py 與 mock 樣本

**Files:** Create `fetchers.py`, `scripts/make_mock_data.py`, `data/mock/*.json`, `tests/test_fetchers_mock.py`

- [ ] **Step 1: fetchers.py**

```python
"""所有外部資料抓取;正規化為 DataFrame。mock 模式讀 data/mock/ 樣本。"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import pandas as pd
import requests

RETRIES = 3
RETRY_WAIT = 2  # 秒
TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0 twstock-dashboard"}

TWSE = "https://openapi.twse.com.tw/v1"
TPEX = "https://www.tpex.org.tw/openapi/v1"

INDEX_SYMBOLS = {
    "^TWII": "台股加權", "^GSPC": "S&P 500", "^IXIC": "那斯達克", "^SOX": "費城半導體",
    "^N225": "日經225", "^KS11": "韓國KOSPI", "000001.SS": "上證指數", "^HSI": "恒生指數",
}

INDUSTRY_NAMES = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維", "05": "電機機械",
    "06": "電器電纜", "07": "化學工業", "08": "玻璃陶瓷", "09": "造紙工業", "10": "鋼鐵工業",
    "11": "橡膠工業", "12": "汽車工業", "14": "建材營造", "15": "航運業", "16": "觀光餐旅",
    "17": "金融保險", "18": "貿易百貨", "19": "綜合", "20": "其他", "21": "化學工業",
    "22": "生技醫療業", "23": "油電燃氣業", "24": "半導體業", "25": "電腦及週邊設備業",
    "26": "光電業", "27": "通信網路業", "28": "電子零組件業", "29": "電子通路業",
    "30": "資訊服務業", "31": "其他電子業", "32": "文化創意業", "33": "農業科技業",
    "34": "電子商務", "35": "綠能環保", "36": "數位雲端", "37": "運動休閒", "38": "居家生活",
}

MOCK_DIR: Path | None = None


def set_mock(mock_dir):
    global MOCK_DIR
    MOCK_DIR = Path(mock_dir) if mock_dir else None


class FetchError(Exception):
    def __init__(self, source: str, cause: Exception):
        super().__init__(f"{source}: {cause}")
        self.source = source


def _load(url: str, source: str, mock_file: str):
    if MOCK_DIR:
        return json.loads((MOCK_DIR / mock_file).read_text(encoding="utf-8"))
    last = None
    for attempt in range(RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001 - 重試後統一包裝
            last = e
            if attempt < RETRIES - 1:
                time.sleep(RETRY_WAIT)
    raise FetchError(source, last)


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return None


def _pick(row: dict, *candidates):
    """欄位名稱容錯:依候選清單取值,再退而求其次找「包含」候選字的鍵。"""
    for c in candidates:
        if c in row:
            return row[c]
    for c in candidates:
        for k in row:
            if c in k:
                return row[k]
    return None


def parse_tw_date(s):
    """支援民國(1150612)與西元(20260612 / 2026-06-12)格式。"""
    if not s:
        return None
    s = str(s).strip().replace("/", "").replace("-", "")
    try:
        if len(s) == 7:
            return dt.date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))
        if len(s) == 8:
            return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None
    return None


def _daily_df(rows, code_keys, name_keys, close_keys, change_keys, value_keys, high_keys, date_keys):
    out = []
    data_date = None
    for r in rows:
        close = _num(_pick(r, *close_keys))
        change = _num(_pick(r, *change_keys))
        turnover = _num(_pick(r, *value_keys))
        code = str(_pick(r, *code_keys) or "").strip()
        if not code or close is None or not turnover:
            continue
        prev = close - change if change is not None else None
        change_pct = (change / prev * 100) if (change is not None and prev) else None
        if data_date is None:
            data_date = parse_tw_date(_pick(r, *date_keys))
        out.append({
            "code": code,
            "name": str(_pick(r, *name_keys) or "").strip(),
            "close": close,
            "high": _num(_pick(r, *high_keys)),
            "change_pct": change_pct,
            "turnover": turnover,
        })
    df = pd.DataFrame(out)
    df.attrs["date"] = data_date
    return df


def fetch_twse_daily() -> pd.DataFrame:
    rows = _load(f"{TWSE}/exchangeReport/STOCK_DAY_ALL", "上市行情", "stock_day_all.json")
    return _daily_df(rows, ["Code", "證券代號"], ["Name", "證券名稱"],
                     ["ClosingPrice", "收盤價"], ["Change", "漲跌價差"],
                     ["TradeValue", "成交金額"], ["HighestPrice", "最高價"], ["Date", "日期"])


def fetch_tpex_daily() -> pd.DataFrame:
    rows = _load(f"{TPEX}/tpex_mainboard_daily_close_quotes", "上櫃行情", "tpex_daily.json")
    return _daily_df(rows, ["SecuritiesCompanyCode", "代號"], ["CompanyName", "名稱"],
                     ["Close", "收盤"], ["Change", "漲跌"],
                     ["TransactionAmount", "成交金額", "TradingAmount"],
                     ["High", "最高"], ["Date", "日期"])


def fetch_industry_map() -> pd.DataFrame:
    """上市 t187ap03_L + 上櫃 t187ap03_O → code, industry, capital(實收資本額)。"""
    rows = []
    rows += _load(f"{TWSE}/opendata/t187ap03_L", "上市產業別", "t187ap03_L.json")
    rows += _load(f"{TWSE}/opendata/t187ap03_O", "上櫃產業別", "t187ap03_O.json")
    out = []
    for r in rows:
        code = str(_pick(r, "公司代號", "Code") or "").strip()
        ind = str(_pick(r, "產業別", "SecuritiesIndustryCode") or "").strip()
        if not code or not ind:
            continue
        out.append({
            "code": code,
            "industry": INDUSTRY_NAMES.get(ind.zfill(2), f"其他({ind})"),
            "capital": _num(_pick(r, "實收資本額", "Capital")) or 0.0,
        })
    return pd.DataFrame(out).drop_duplicates("code")


def _inst_df(rows, code_keys, net_keys):
    out = []
    for r in rows:
        code = str(_pick(r, *code_keys) or "").strip()
        net = _num(_pick(r, *net_keys))
        if code and net is not None:
            out.append({"code": code, "inst_net_shares": net})
    return pd.DataFrame(out)


def fetch_institutional() -> pd.DataFrame:
    """三大法人個股買賣超股數(上市 T86 + 上櫃)。"""
    twse_rows = _load(f"{TWSE}/fund/T86", "三大法人(上市)", "t86.json")
    tpex_rows = _load(f"{TPEX}/tpex_3insti_daily_trading", "三大法人(上櫃)", "tpex_inst.json")
    a = _inst_df(twse_rows, ["Code", "證券代號"],
                 ["TotalDifference", "三大法人買賣超股數", "Total"])
    b = _inst_df(tpex_rows, ["SecuritiesCompanyCode", "Code", "代號"],
                 ["TotalDifference", "三大法人買賣超股數合計", "三大法人買賣超股數", "Total"])
    return pd.concat([a, b], ignore_index=True)


def fetch_indices():
    """yfinance 近60日收盤;個別失敗不阻斷,回傳 (dict[symbol→Series], failed)。"""
    if MOCK_DIR:
        raw = json.loads((MOCK_DIR / "indices.json").read_text(encoding="utf-8"))
        return ({sym: pd.Series(v["closes"], index=v["dates"], dtype=float)
                 for sym, v in raw.items()}, [])
    import yfinance as yf
    series, failed = {}, []
    for sym in INDEX_SYMBOLS:
        try:
            hist = yf.Ticker(sym).history(period="3mo")["Close"].dropna().tail(60)
            if hist.empty:
                raise ValueError("empty history")
            hist.index = [d.strftime("%Y-%m-%d") for d in hist.index]
            series[sym] = hist
        except Exception:  # noqa: BLE001 - 單一指數失敗不阻斷其餘
            failed.append(sym)
    return series, failed
```

- [ ] **Step 2: mock 產生器 `scripts/make_mock_data.py`**(定值亂數,4個產業×12檔上市+4檔上櫃,日期=執行當日,寫出 6 個 json)

```python
"""產生 data/mock/ 樣本,使 --mock 可離線跑通全流程。"""
import datetime as dt
import json
import random
from pathlib import Path

random.seed(42)
ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "data/mock"
MOCK.mkdir(parents=True, exist_ok=True)
TODAY = dt.date.today()
DATE8 = TODAY.strftime("%Y%m%d")

TWSE_STOCKS = [  # (code, name, 產業代碼)
    ("2330", "台積電", "24"), ("2303", "聯電", "24"), ("3034", "聯詠", "24"),
    ("2317", "鴻海", "31"), ("2382", "廣達", "25"), ("3231", "緯創", "25"),
    ("2603", "長榮", "15"), ("2609", "陽明", "15"), ("2615", "萬海", "15"),
    ("2881", "富邦金", "17"), ("2882", "國泰金", "17"), ("2891", "中信金", "17"),
]
TPEX_STOCKS = [("5483", "中美晶", "24"), ("3105", "穩懋", "24"),
               ("5274", "信驊", "24"), ("8069", "元太", "31")]


def w(name, obj):
    (MOCK / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def quote(code, name, base):
    close = round(base * random.uniform(0.95, 1.08), 2)
    change = round(close * random.uniform(-0.03, 0.05), 2)
    return code, name, close, change, random.randint(2, 80) * 10**8


w("stock_day_all.json", [
    {"Date": DATE8, "Code": c, "Name": n, "ClosingPrice": str(cl), "Change": str(ch),
     "HighestPrice": str(round(cl * 1.01, 2)), "TradeValue": str(tv)}
    for c, n, cl, ch, tv in (quote(c, n, random.uniform(50, 1000)) for c, n, _ in TWSE_STOCKS)])

w("tpex_daily.json", [
    {"Date": DATE8, "SecuritiesCompanyCode": c, "CompanyName": n, "Close": str(cl),
     "Change": str(ch), "High": str(round(cl * 1.01, 2)), "TransactionAmount": str(tv)}
    for c, n, cl, ch, tv in (quote(c, n, random.uniform(30, 400)) for c, n, _ in TPEX_STOCKS)])

w("t187ap03_L.json", [
    {"公司代號": c, "公司簡稱": n, "產業別": ind, "實收資本額": str(random.randint(50, 2600) * 10**8)}
    for c, n, ind in TWSE_STOCKS])
w("t187ap03_O.json", [
    {"公司代號": c, "公司簡稱": n, "產業別": ind, "實收資本額": str(random.randint(20, 300) * 10**8)}
    for c, n, ind in TPEX_STOCKS])

w("t86.json", [{"Code": c, "Name": n, "TotalDifference": str(random.randint(-8000, 12000) * 1000)}
               for c, n, _ in TWSE_STOCKS])
w("tpex_inst.json", [{"SecuritiesCompanyCode": c, "CompanyName": n,
                      "TotalDifference": str(random.randint(-3000, 5000) * 1000)}
                     for c, n, _ in TPEX_STOCKS])

dates = []
d = TODAY - dt.timedelta(days=90)
while len(dates) < 60:
    if d.weekday() < 5:
        dates.append(d.strftime("%Y-%m-%d"))
    d += dt.timedelta(days=1)
indices = {}
for sym in ["^TWII", "^GSPC", "^IXIC", "^SOX", "^N225", "^KS11", "000001.SS", "^HSI"]:
    level = random.uniform(3000, 25000)
    closes = []
    for _ in dates:
        level *= 1 + random.uniform(-0.015, 0.018)
        closes.append(round(level, 2))
    indices[sym] = {"dates": dates, "closes": closes}
w("indices.json", indices)
print("mock data written to", MOCK)
```

- [ ] **Step 3: smoke 測試 `tests/test_fetchers_mock.py`**

```python
from pathlib import Path

import fetchers

MOCK = Path(__file__).resolve().parents[1] / "data/mock"


def setup_module():
    fetchers.set_mock(MOCK)


def teardown_module():
    fetchers.set_mock(None)


def test_mock_daily_quotes():
    twse, tpex = fetchers.fetch_twse_daily(), fetchers.fetch_tpex_daily()
    assert len(twse) == 12 and len(tpex) == 4
    assert {"code", "close", "change_pct", "turnover"} <= set(twse.columns)
    assert twse.attrs["date"] is not None


def test_mock_industry_and_institutional():
    ind = fetchers.fetch_industry_map()
    assert len(ind) == 16
    assert "半導體業" in set(ind["industry"])
    inst = fetchers.fetch_institutional()
    assert len(inst) == 16


def test_mock_indices():
    series, failed = fetchers.fetch_indices()
    assert failed == [] and len(series) == 8
    assert len(series["^TWII"]) == 60
```

- [ ] **Step 4: 執行** `.venv/bin/python scripts/make_mock_data.py` 然後 `.venv/bin/pytest tests/ -v` → 全部 PASS
- [ ] **Step 5: Commit** `feat: fetchers 與 mock 樣本`

### Task 7: run.py 管線

**Files:** Create `run.py`

- [ ] **Step 1: 實作 run.py**

```python
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
HISTORY_DIR = ROOT / "data/history"
DATA_JS = ROOT / "web/data.js"
CHART_SYMBOLS = ["^TWII", "^SOX", "^GSPC"]


def load_history() -> list:
    files = sorted(HISTORY_DIR.glob("*.json"))
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def prior_highs_from_history(history: list, window: int = 20) -> dict:
    highs: dict = {}
    for day in history[-window:]:
        for s in day.get("stocks", []):
            c = s["code"]
            highs[c] = max(highs.get(c, 0.0), s["close"])
    return highs


def build_stocks(twse, tpex, industry, inst) -> pd.DataFrame:
    df = pd.concat([twse, tpex], ignore_index=True)
    df = df.merge(industry, on="code", how="left").merge(inst, on="code", how="left")
    df["inst_net_value"] = (df["inst_net_shares"].fillna(0.0)) * df["close"]
    df["market_cap"] = df["capital"].fillna(0.0) / 10.0 * df["close"]  # 面額10元近似
    return df


def fetch_with_fallback(history: list):
    """各來源獨立失敗處理:沿用最近快照之該部分,記入 stale。"""
    stale = []
    last = history[-1] if history else None

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
        industry = fetchers.fetch_industry_map()
    except fetchers.FetchError as e:
        industry = pd.DataFrame(columns=["code", "industry", "capital"])
        stale.append(e.source)
    try:
        inst = fetchers.fetch_institutional()
    except fetchers.FetchError as e:
        inst = pd.DataFrame(columns=["code", "inst_net_shares"])
        stale.append(e.source)

    indices, failed = fetchers.fetch_indices()
    if failed and last:
        for sym in failed:
            snap = last.get("indices", {}).get(sym)
            if snap:
                indices[sym] = pd.Series(snap["closes"], index=snap["dates"], dtype=float)
        stale.append("國際指數(" + ",".join(failed) + ")")
    elif failed:
        stale.append("國際指數(" + ",".join(failed) + ")")
    return twse, tpex, industry, inst, indices, stale


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
    args = ap.parse_args()
    if args.mock:
        fetchers.set_mock(ROOT / "data/mock")

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    history = load_history()
    twse, tpex, industry, inst, indices, stale = fetch_with_fallback(history)

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

    stocks = build_stocks(twse, tpex, industry, inst)
    history = [h for h in history if h["date"] != date_str]  # 同日重跑覆蓋
    prior_highs = prior_highs_from_history(history)
    sectors = scoring.aggregate_sectors(stocks, prior_highs)

    total_turnover = float(stocks["turnover"].sum())
    market_change = float((stocks["change_pct"].fillna(0) * stocks["turnover"]).sum()
                          / total_turnover) if total_turnover else 0.0

    snapshot = {
        "date": date_str,
        "market_change_pct": round(market_change, 4),
        "stocks": [{"code": r.code, "close": r.close, "turnover": r.turnover}
                   for r in stocks.itertuples() if pd.notna(r.close)],
        "sectors": {idx: {k: (float(v) if pd.notna(v) else 0.0) for k, v in row.items()}
                    for idx, row in sectors.iterrows()},
        "indices": {sym: {"dates": list(s.index), "closes": [float(x) for x in s]}
                    for sym, s in indices.items()},
    }
    scores = scoring.compute_breakout_scores(history + [snapshot])

    breakout = []
    for ind_name, row in scores.iterrows():
        past = [d["sectors"][ind_name]["score"] for d in history[-2:]
                if ind_name in d["sectors"] and "score" in d["sectors"][ind_name]]
        arrow = scoring.score_arrow(past + [float(row["score"])])
        sec_stocks = stocks[(stocks["industry"] == ind_name) & (stocks["inst_net_value"] > 0)]
        top5 = sec_stocks.nlargest(5, "inst_net_value")
        breakout.append({
            "industry": ind_name,
            "score": float(row["score"]),
            "arrow": arrow,
            "detail": {k: round(float(row[k]), 4) for k in
                       ["vol_slope", "high_delta", "inst_strength", "inst_streak", "ret20", "rs_turn"]},
            "top_inst_stocks": [{"code": r.code, "name": r.name,
                                 "net_value": round(float(r.inst_net_value))}
                                for r in top5.itertuples()],
        })
        snapshot["sectors"][ind_name]["score"] = float(row["score"])

    (HISTORY_DIR / f"{date_str}.json").write_text(
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
        "breakout": breakout,
    }
    DATA_JS.parent.mkdir(parents=True, exist_ok=True)
    DATA_JS.write_text("window.DASHBOARD_DATA = "
                       + json.dumps(payload, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"完成:{date_str},族群 {len(hot)} 個,快照與 web/data.js 已更新"
          + (f";資料延遲:{','.join(stale)}" if stale else ""))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 驗證** `.venv/bin/python run.py --mock` → 印出「完成:…」;檢查 `web/data.js` 與 `data/history/*.json` 內容合理(族群數=4 左右、分數 0–100)
- [ ] **Step 3: 連跑第二次確認同日覆蓋不會重複累積歷史**
- [ ] **Step 4: Commit** `feat: run.py 管線`

### Task 8: web/dashboard.html

**Files:** Create `web/dashboard.html`

- [ ] **Step 1: 完整單檔前端**(內嵌 CSS/JS;台股慣例紅漲綠跌;黃色 stale 標籤;F1 卡片+可勾選折線圖+相關係數;F2 Top10 表+占比橫條圖;F3 評分表+箭頭+展開明細)— 完整 HTML 見執行時實作,結構:

```html
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8">
  <title>台股分析儀表板</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>/* 深色主題、卡片格線、表格、.up 紅 .down 綠、.badge 黃 */</style>
</head>
<body>
  <h1>台股分析儀表板</h1><div id="meta"></div><div id="stale"></div>
  <section id="f1"><div id="index-cards"></div>
    <div id="series-toggles"></div><canvas id="index-chart"></canvas><div id="corr"></div></section>
  <section id="f2"><table id="hot-table"></table><canvas id="share-chart"></canvas></section>
  <section id="f3"><table id="score-table"></table></section>
  <script src="data.js"></script>
  <script>/* render(D):卡片、Chart.js line(勾選切換 dataset.hidden)、橫條圖、
            評分表 click 展開明細列(子項分數+法人買超前5名個股) */</script>
</body>
</html>
```

- [ ] **Step 2: 驗證** `open web/dashboard.html`(mock 資料)— 三區塊皆渲染、無 console error
- [ ] **Step 3: Commit** `feat: 儀表板前端`

### Task 9: README 與收尾

**Files:** Create `README.md`

- [ ] **Step 1: README**(安裝、`python run.py` 用法、--mock、歷史快照說明、資料來源、已知近似:市值與法人金額估算)
- [ ] **Step 2: 全部測試最終驗證** `.venv/bin/pytest tests/ -v` + `.venv/bin/python run.py --mock`
- [ ] **Step 3: Commit** `docs: README`

## Self-Review 紀錄

- 規格覆蓋:F1(Task 3/7/8)、F2(Task 4/7/8)、F3(Task 5/7/8)、歷史快照(Task 7)、休市判定/重試/單源fallback/yfinance個別失敗(Task 6/7)、pytest a/b/c(Task 2/5)、--mock(Task 6)。
- 型別一致:快照 schema 在 Task 5 註明、Task 7 產生、scoring `_series` 消費,欄位名一致(turnover_share/avg_change_pct/new_high_count/inst_net_value/market_cap/score)。
- 已知妥協:TPEx 與 T86 真實欄位名可能與候選清單有出入 → `_pick` 容錯 + 單源 fallback 機制兜底;首次上線前 20 日「創新高/20日漲幅」以可得天數近似。
