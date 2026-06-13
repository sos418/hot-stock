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


# 強勢股(漲幅>8%):讓 --mock 能展示 F3 今日強勢族群
STRONG_CODES = {"2330", "2303", "2317", "2382"}  # 晶圓製造×2、AI伺服器×2


def quote(code, name, base):
    close = round(base * random.uniform(0.95, 1.08), 2)
    pct = random.uniform(0.085, 0.095) if code in STRONG_CODES else random.uniform(-0.03, 0.05)
    change = round(close * pct, 2)  # change/prev ≈ pct/(1-pct);0.085→約 +9.3%
    return code, name, close, change, random.randint(2, 80) * 10**8


# TWSE rwd 回應格式(www.twse.com.tw/rwd/...):{stat, date, fields, data}
w("stock_day_all.json", {
    "stat": "OK", "date": DATE8,
    "fields": ["證券代號", "證券名稱", "成交股數", "成交金額", "開盤價",
               "最高價", "最低價", "收盤價", "漲跌價差", "成交筆數"],
    "data": [[c, n, "1,000,000", f"{tv:,}", str(cl), str(round(cl * 1.01, 2)),
              str(round(cl * 0.97, 2)), str(cl), ("+" if ch >= 0 else "") + str(ch), "5,000"]
             for c, n, cl, ch, tv in
             (quote(c, n, random.uniform(50, 1000)) for c, n, _ in TWSE_STOCKS)]})

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

w("t86.json", {
    "stat": "OK", "date": DATE8,
    "fields": ["證券代號", "證券名稱", "三大法人買賣超股數"],
    "data": [[c, n, f"{random.randint(-8000, 12000) * 1000:,}"] for c, n, _ in TWSE_STOCKS]})
w("tpex_inst.json", [{"SecuritiesCompanyCode": c, "CompanyName": n,
                      "TotalDifference": str(random.randint(-3000, 5000) * 1000)}
                     for c, n, _ in TPEX_STOCKS])

# 產業價值鏈族群(層級:鏈=大傘 group==chain;細分類=子群)
# 半導體鏈含晶圓製造/記憶體IC兩子群;其餘僅鏈層級
CHAINS = {
    "半導體": {"晶圓製造": ["2330", "2303", "5483", "3105"],
             "記憶體IC": ["3034", "5274", "8069"]},
    "AI伺服器": {None: ["2317", "2382", "3231"]},
    "貨櫃航運": {None: ["2603", "2609", "2615"]},
    "金控": {None: ["2881", "2882", "2891"]},
}
chain_rows = []
for chain, subs in CHAINS.items():
    members = set()
    for sub, codes in subs.items():
        members.update(codes)
        if sub:
            chain_rows += [{"code": c, "group": sub, "chain": chain} for c in codes]
    chain_rows += [{"code": c, "group": chain, "chain": chain} for c in members]  # 鏈層級大傘
w("industry_chains.json", {"fetched_at": TODAY.isoformat(), "groups": chain_rows})

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
