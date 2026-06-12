# 族群分類改用產業價值鏈細分類 設計規格
日期:2026-06-12 狀態:使用者已核准(來源=官方產業價值鏈、粒度=細分類、取代現有分類)

## 目的
F2 熱門族群與 F3 突破口評分的分群,由證交所粗分類(35 個產業別)改為
官方「產業價值鏈資訊平台」(ic.tpex.org.tw)的分類,貼近實際題材族群。

實作時依實際頁面結構修訂為**三層聯集**(經使用者範例驗證:「半導體」是
鏈層級、「被動元件/封測」是主分類、「記憶體IC」是細分類):
產業鏈(44條)∪ 主分類(companyList 區塊)∪ 細分類(sc_company 表格)。

## 資料來源與快取
- 來源:`https://ic.tpex.org.tw/introduce.php?ic=<chain>`,chain 代碼自首頁
  解析(目前 31 條)。每頁含 `<table id="sc_company_*">` 個股表,表前最近的
  粗體標題為細分類名;個股代號取 `company_basic.php?stk_code=NNNN`。
- 快取:解析結果寫 `data/industry_chains.json`
  (`{"fetched_at": "YYYY-MM-DD", "groups": [{"code","group"},...]}`)。
  7 天內直接用快取;過期自動重抓;重抓失敗沿用舊快取並標示「資料延遲:產業分類」。
  `run.py --refresh-industry` 強制更新。
- 細分類名清洗:去 `&nbsp;`、空白、結尾 `(N家)`;跨產業鏈同名時加
  「<產業鏈名>-」前綴消歧;同一(細分類, 代號)去重。
- 既有 `fetch_industry_map()`(t187ap03_L/O)僅保留「實收資本額」用途,
  更名 `fetch_capital_map()` 回傳 code, capital。

## 彙總語意變更
- **一檔多族群**:個股可屬多個細分類,彙總前 explode 成 (個股, 族群) 列。
- **成交占比分母改為全市場成交金額**(`aggregate_sectors` 新增
  `market_turnover` 參數;未提供時退回族群加總,維持舊測試語意)。
  族群占比加總不再等於 100%,屬正確語意。
- **雜訊過濾**:`MIN_GROUP_SIZE = 3`,當日有成交之成員數 <3 的族群不進
  熱度榜/評分(`aggregate_sectors` 輸出 `member_count` 欄,run.py 過濾)。
- 未被平台分類之個股不參與族群統計(仍計入全市場分母與大盤漲跌)。

## 不變項
- 歷史快照格式不變;族群鍵改變後舊鍵自然被 `_series` 忽略,
  箭頭重新「資料累積中」3 日。
- F1 國際大盤、評分公式、休市判定、單源 fallback 機制均不變。

## 前端
- 結構不變;F2 橫條圖僅畫成交占比 Top 20;F3 表全列依評分排序。

## 測試
- 解析器:以 `tests/fixtures/chain_sample.html`(真實頁面節錄)驗證
  細分類名清洗、去重、stk_code 抽取。
- `aggregate_sectors`:多重歸屬、market_turnover 分母、member_count。
- mock:新增 `data/mock/industry_chains.json`,`--mock` 全流程照常跑通。

## 風險
平台 HTML 改版需小幅維護解析器;以快取沿用+黃色延遲標籤兜底。
