# 產業價值鏈細分類族群 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 `docs/superpowers/specs/2026-06-12-industry-chain-groups-design.md`,把 F2/F3 分群從證交所產業別改為 ic.tpex.org.tw 產業價值鏈(主分類∪細分類聯集,一檔多族群)。

**Architecture:** fetchers 新增 chain 解析(純函式 `parse_chain_page` 可測)+ 7天快取;scoring.aggregate_sectors 增加 `market_turnover` 分母與 `member_count`;run.py 改以 (個股,族群) 多對多 explode 彙總並過濾小族群;前端橫條圖只取 Top 20。

**Tech Stack:** 既有(Python/pandas/requests + vanilla JS)。

**已實證的解析事實**(2026-06-12 對 D000 真實頁面驗證):
- `<div id="companyList_XXXX" title="主分類名">` 隱藏區塊 → 主分類完整清單(IC封裝測試34家…)
- `<table id="sc_company_XXXX">` 前最近視窗內的 `<b>標題</b>`(過濾「本國上市/上櫃/興櫃/外國」章節標籤)→ 細分類(記憶體IC6家…);每表在頁內出現兩次(圖示區無標題自動跳過),(族群,代號) 去重即可
- 個股代號:`stk_code=NNNN`;產業鏈名:`<title>… > (.+?)產業鏈簡介`
- 首頁 `ic=[A-Z][0-9]{3}` 共 31 條鏈

---

### Task 1: fetchers — chain 解析純函式(TDD)

**Files:** Modify `fetchers.py`, Create `tests/test_chain_parser.py`, `tests/fixtures/chain_sample.html`

- [ ] **Step 1: fixture** — 自製小型 HTML(含兩種結構、重複表格、章節標籤、`(N家)`、`&nbsp;`):

```html
<html><head><title> 產業價值鏈資訊平台 > 測試產業鏈簡介</title></head><body>
<div class="panel">
  <table id="sc_company_T110"><tr><td><b>本國上市公司(2家)</b></td>
  <td><a href="company_basic.php?stk_code=1111">甲</a></td>
  <td><a href="company_basic.php?stk_code=2222">乙</a></td></tr></table>
</div>
<div class="list"><b>主分A</b><div><b>細分&nbsp;X&nbsp;(2家)</b>
  <table id="sc_company_T110"><tr><td><b>本國上市公司(2家)</b></td>
  <td><a href="company_basic.php?stk_code=1111">甲</a></td>
  <td><a href="company_basic.php?stk_code=2222">乙</a></td></tr></table></div></div>
<div id="companyList_TA00" title="主分A"><div class="company-list"><table><tr>
  <td><a href="company_basic.php?stk_code=1111">甲</a></td>
  <td><a href="company_basic.php?stk_code=2222">乙</a></td>
  <td><a href="company_basic.php?stk_code=3333">丙</a></td></tr></table></div></div>
<div id="companyList_TB00" title="主分B"><div class="company-list"><table><tr>
  <td><a href="company_basic.php?stk_code=4444">丁</a></td></tr></table></div></div>
</body></html>
```

- [ ] **Step 2: 失敗測試**

```python
from pathlib import Path

import fetchers

HTML = (Path(__file__).parent / "fixtures/chain_sample.html").read_text(encoding="utf-8")


def test_parse_chain_name():
    assert fetchers.parse_chain_name(HTML) == "測試"


def test_parse_chain_page_levels_and_dedupe():
    pairs = fetchers.parse_chain_page(HTML)
    assert ("細分 X", "1111") in pairs          # 細分類:清洗 &nbsp; 與 (N家)
    assert ("主分A", "3333") in pairs           # 主分類 companyList
    assert ("本國上市公司", "1111") not in pairs  # 章節標籤不可當族群
    assert len([p for p in pairs if p[0] == "細分 X"]) == 2  # 重複表格已去重
    assert ("主分B", "4444") in pairs
```

- [ ] **Step 3: 確認失敗**(AttributeError)
- [ ] **Step 4: 實作**(加在 fetchers.py;`html` 標準庫以 `import html as html_lib` 引入避免撞名)

```python
CHAIN_SECTION_PAT = re.compile(r"(本國上市|本國上櫃|本國興櫃|外國|僑外)")


def _clean_group_name(name: str) -> str:
    name = html_lib.unescape(name).replace("\xa0", " ").strip()
    return re.sub(r"[\(\(]\s*\d+\s*家\s*[\)\)]\s*$", "", name).strip()


def parse_chain_name(page: str) -> str:
    m = re.search(r"<title>[^<]*>\s*(.+?)產業鏈簡介", page)
    return m.group(1).strip() if m else ""


def parse_chain_page(page: str) -> set:
    """單一產業鏈頁 → {(族群名, 股票代號)};主分類(companyList div)∪細分類(sc_company 表)。"""
    pairs = set()
    # 主分類:隱藏 companyList 區塊,title 屬性即族群名
    for seg in re.split(r'<div id="companyList_[A-Z0-9]+" title="', page)[1:]:
        title = _clean_group_name(seg.split('"', 1)[0])
        if not title or CHAIN_SECTION_PAT.search(title):
            continue
        for code in re.findall(r"stk_code=([0-9A-Za-z]+)", seg.split("</div></div>", 1)[0]):
            pairs.add((title, code))
    # 細分類:sc_company 表格,標題取「前一表結尾~本表」視窗內最後一個非章節 <b>
    prev_end = 0
    for m in re.finditer(r'<table id="sc_company_[A-Z0-9]+"[^>]*>(.*?)</table>', page, re.S):
        window = page[prev_end:m.start()]
        prev_end = m.end()
        titles = [_clean_group_name(t) for t in re.findall(r"<b>([^<]+)</b>", window)]
        titles = [t for t in titles if t and not CHAIN_SECTION_PAT.search(t)]
        if not titles:
            continue
        for code in re.findall(r"stk_code=([0-9A-Za-z]+)", m.group(1)):
            pairs.add((titles[-1], code))
    return pairs
```

- [ ] **Step 5: 測試通過 → Commit** `feat: 產業價值鏈頁面解析`

### Task 2: fetchers — fetch_chain_groups 快取與跨鏈彙整

**Files:** Modify `fetchers.py`, `tests/test_fetchers_mock.py`

- [ ] **Step 1: 失敗測試**(mock 模式直接讀樣本)

```python
def test_mock_chain_groups():
    df, stale = fetchers.fetch_chain_groups(Path("/tmp/nonexistent.json"))
    assert stale is False
    assert {"code", "group"} <= set(df.columns)
    assert (df["group"] == "晶圓製造").sum() >= 3
```

- [ ] **Step 2: 實作**

```python
IC_HOME = "https://ic.tpex.org.tw/"
CHAIN_CACHE_DAYS = 7


def _get_text(url: str, source: str) -> str:
    last = None
    for attempt in range(RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < RETRIES - 1:
                time.sleep(RETRY_WAIT)
    raise FetchError(source, last)


def _crawl_chain_groups() -> pd.DataFrame:
    """爬 31 條產業鏈 → DataFrame[code, group];跨鏈同名族群加「鏈名-」前綴消歧。"""
    home = _get_text(IC_HOME, "產業分類")
    chains = sorted(set(re.findall(r"ic=([A-Z][0-9]{3})", home)))
    if not chains:
        raise FetchError("產業分類", ValueError("首頁無產業鏈代碼"))
    by_group: dict = {}   # group -> {chain: set(codes)}
    for ic in chains:
        page = _get_text(f"{IC_HOME}introduce.php?ic={ic}", f"產業分類({ic})")
        chain_name = parse_chain_name(page) or ic
        for group, code in parse_chain_page(page):
            by_group.setdefault(group, {}).setdefault(chain_name, set()).add(code)
        time.sleep(0.5)  # 禮貌間隔
    rows = []
    for group, chains_map in by_group.items():
        ambiguous = len(chains_map) > 1
        for chain_name, codes in chains_map.items():
            name = f"{chain_name}-{group}" if ambiguous else group
            rows.extend({"code": c, "group": name} for c in codes)
    return pd.DataFrame(rows).drop_duplicates()


def fetch_chain_groups(cache_path: Path, force: bool = False):
    """回傳 (DataFrame[code, group], stale)。快取 7 天;重抓失敗沿用舊快取(stale=True)。"""
    if MOCK_DIR:
        raw = json.loads((MOCK_DIR / "industry_chains.json").read_text(encoding="utf-8"))
        return pd.DataFrame(raw["groups"]), False
    cached = None
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        age = (dt.date.today() - dt.date.fromisoformat(cached["fetched_at"])).days
        if not force and age < CHAIN_CACHE_DAYS:
            return pd.DataFrame(cached["groups"]), False
    try:
        df = _crawl_chain_groups()
    except FetchError:
        if cached:
            return pd.DataFrame(cached["groups"]), True
        raise
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(
        {"fetched_at": dt.date.today().isoformat(),
         "groups": df.to_dict("records")}, ensure_ascii=False), encoding="utf-8")
    return df, False
```

- [ ] **Step 3: `fetch_industry_map` 更名 `fetch_capital_map`**,回傳 code, capital(移除 industry 欄與 INDUSTRY_NAMES 對照;t187ap03 來源不變),並同步改 `tests/test_fetchers_mock.py::test_mock_industry_and_institutional` 斷言為 capital 欄位
- [ ] **Step 4: mock 樣本** — `scripts/make_mock_data.py` 產出 `industry_chains.json`:晶圓製造(2330,2303,5483,3105)、記憶體IC(3034,5274,8069)、AI伺服器(2317,2382,3231)、貨櫃航運(2603,2609,2615)、金控(2881,2882,2891)、迷你族群(2330,2317)←驗證 <3 過濾
- [ ] **Step 5: 重產 mock、全測試通過 → Commit** `feat: 產業價值鏈快取與抓取`

### Task 3: scoring — aggregate_sectors 市場分母與成員數(TDD)

**Files:** Modify `scoring.py`, `tests/test_scoring.py`

- [ ] **Step 1: 失敗測試**

```python
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
```

- [ ] **Step 2: 實作** — 簽名 `aggregate_sectors(stocks, prior_highs, market_turnover=None)`;`member_count = g["code"].nunique()`;`total = market_turnover or out["turnover"].sum()`
- [ ] **Step 3: 全測試通過 → Commit** `feat: 族群彙總支援市場分母與成員數`

### Task 4: run.py 接線

**Files:** Modify `run.py`

- [ ] **Step 1:** `--refresh-industry` 參數;常數 `MIN_GROUP_SIZE = 3`、`CHAIN_CACHE = ROOT/"data/industry_chains.json"`
- [ ] **Step 2:** `fetch_with_fallback` 增加 groups:`groups, chain_stale = fetchers.fetch_chain_groups(CHAIN_CACHE, force=args.refresh_industry)`,chain_stale 時 stale.append("產業分類");capital 改 `fetch_capital_map()`
- [ ] **Step 3:** 彙總改為:

```python
member_rows = stocks.merge(groups.rename(columns={"group": "industry"}), on="code")
sectors = scoring.aggregate_sectors(member_rows, prior_highs, market_turnover=total_turnover)
sectors = sectors[sectors["member_count"] >= MIN_GROUP_SIZE]
```

top_inst_stocks / sec_stocks 改用 `member_rows`;snapshot["sectors"] 排除 member_count 以外照舊(member_count 一併存入無妨)
- [ ] **Step 4:** `--mock` 與真實各跑一次驗證;同日覆蓋正常 → Commit `feat: run.py 改用產業價值鏈族群`

### Task 5: 前端與文件

**Files:** Modify `web/dashboard.html`, `README.md`

- [ ] **Step 1:** share-chart 改 `D.sectors_hot.slice(0, 20)`,標題註明「Top 20,占比分母=全市場(個股可屬多族群)」
- [ ] **Step 2:** headless Chrome 截圖驗證
- [ ] **Step 3:** README 資料來源表加產業價值鏈、語意說明(多重歸屬/分母/MIN_GROUP_SIZE/快取7天/--refresh-industry)
- [ ] **Step 4:** 全測試 + 真實執行最終驗證 → Commit `feat: 儀表板改用產業價值鏈族群分類`

## Self-Review 紀錄
- 規格覆蓋:來源+快取(T2)、解析(T1)、多重歸屬與分母(T3/T4)、過濾(T4)、前端(T5)、mock(T2)、stale 標籤(T4)。
- 型別一致:fetch_chain_groups 回 (df[code,group], stale);run.py rename group→industry 後餵 aggregate_sectors,與既有欄位約定一致。
- 已知妥協:31 頁爬取每 7 天一次約 9MB;細分類僅部分節點提供,主分類補齊覆蓋。
