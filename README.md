# 台股分析儀表板

盤後執行一次,產出本機網頁儀表板,回答三個問題:

1. 重要國家大盤今天表現如何?(F1)
2. 今天的資金集中在哪些產業族群?(F2)
3. 哪些族群正在醞釀突破?(F3 突破口綜合評分 0–100)

規格見 `doc/2026-06-11-twstock-dashboard-design.md`。

## 安裝

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 使用

```bash
# 收盤後(建議 15:00 之後,待證交所資料更新)執行
.venv/bin/python run.py

# 雙擊或開啟 web/dashboard.html 於瀏覽器檢視
open web/dashboard.html
```

- 無伺服器、無資料庫;每日彙總與評分沉澱於 `data/history/YYYY-MM-DD.json`(同日重跑會覆蓋)。
- 休市或資料未更新時印出「今日休市/資料未更新」並退出,不覆寫既有輸出。
- 單一來源失敗時自動沿用最近一份歷史快照之該部分,頁面以黃色標籤標示「資料延遲:來源名」。

### 離線測試(mock)

```bash
.venv/bin/python scripts/make_mock_data.py   # 產生 data/mock/ 樣本(已附)
.venv/bin/python run.py --mock               # 以本地樣本跑通全流程
.venv/bin/pytest tests/ -v                   # scoring 單元測試 + mock smoke
```

mock 模式的快照寫入 `data/mock_history/`,不會污染真實的 `data/history/`;
但 `web/data.js` 會被覆寫,之後重跑一次 `run.py` 即恢復真實資料。

## 資料來源(免費、免金鑰)

| 用途 | 來源 |
|---|---|
| 國際指數近60日 | yfinance |
| 上市個股日成交 | TWSE rwd `afterTrading/STOCK_DAY_ALL` |
| 上市產業別 | TWSE OpenAPI `opendata/t187ap03_L` |
| 上櫃產業別 | TPEx OpenAPI `mopsfin_t187ap03_O` |
| 上櫃個股日成交 | TPEx OpenAPI `tpex_mainboard_daily_close_quotes` |
| 三大法人買賣超 | TWSE rwd `fund/T86`、TPEx OpenAPI `tpex_3insti_daily_trading` |

> 為何上市行情用 rwd 而非 OpenAPI:`openapi.twse.com.tw` 的行情/法人鏡像
> 約「隔日清晨 05:20」才更新,當日盤後執行會誤判為「資料未更新」;
> 官網 rwd 端點當天盤後即有(行情約 15:00、T86 約 16:30 後)。
> 建議 16:30 之後執行,法人資料才完整(否則頁面標示「資料延遲:三大法人(上市)」)。

## 評分邏輯摘要(F3)

- 量能 40:成交占比5日斜率(20)+創20日新高家數3日變化(20)
- 籌碼 30:法人近3日買超/類股市值(15)+法人連續買超天數(15)
- 輪動 30:20日漲幅後50%低基期(15)+5日相對強度由負轉正(15)
- 各連續子項以全族群分位數 `(rank-1)/(n-1)` 正規化後加權
- 近3日評分「連升」才顯示↑;歷史不足3日顯示「資料累積中」

## 已知近似(免費資料限制)

- 類股總市值 ≈ Σ(實收資本額/10 × 收盤價),以面額10元估算股數。
- 法人買超金額 ≈ 買賣超股數 × 收盤價(免費端點僅提供股數)。
- 創20日新高、20日漲幅等跨日指標由 `data/history/` 快照累積;上線初期天數不足時以可得天數近似計算。
