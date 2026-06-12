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
