"""所有外部資料抓取;正規化為 DataFrame。mock 模式讀 data/mock/ 樣本。"""
from __future__ import annotations

import datetime as dt
import html as html_lib
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

RETRIES = 3
RETRY_WAIT = 2  # 秒
TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0 twstock-dashboard"}

TWSE = "https://openapi.twse.com.tw/v1"
# 注意:openapi.twse.com.tw 的行情/法人鏡像「隔日清晨」才更新,
# 盤後當日資料須改用官網 rwd 端點(約 15:00–16:30 後可得)。
TWSE_RWD = "https://www.twse.com.tw/rwd/zh"
TPEX = "https://www.tpex.org.tw/openapi/v1"

INDEX_SYMBOLS = {
    "^TWII": "台股加權", "^GSPC": "S&P 500", "^IXIC": "那斯達克", "^SOX": "費城半導體",
    "^N225": "日經225", "^KS11": "韓國KOSPI", "000001.SS": "上證指數", "^HSI": "恒生指數",
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
        except Exception as e:  # noqa: BLE001 - 重試後統一包裝為 FetchError
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
    """欄位名稱容錯:先精確比對候選清單,再退而求其次找「包含」候選字的鍵。"""
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


def _rwd_rows(payload) -> list:
    """TWSE rwd 回應 {stat, date, fields, data} → list[dict];休市/查無資料回空。"""
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return []
    fields = payload.get("fields", [])
    date = payload.get("date")
    rows = []
    for arr in payload.get("data", []):
        r = dict(zip(fields, arr))
        r.setdefault("日期", date)
        rows.append(r)
    return rows


def fetch_twse_daily() -> pd.DataFrame:
    """上市個股日成交。回傳 code,name,close,high,change_pct,turnover;attrs['date']=資料日期。"""
    payload = _load(f"{TWSE_RWD}/afterTrading/STOCK_DAY_ALL?response=json",
                    "上市行情", "stock_day_all.json")
    rows = _rwd_rows(payload)
    return _daily_df(rows, ["Code", "證券代號"], ["Name", "證券名稱"],
                     ["ClosingPrice", "收盤價"], ["Change", "漲跌價差"],
                     ["TradeValue", "成交金額"], ["HighestPrice", "最高價"], ["Date", "日期"])


def fetch_tpex_daily() -> pd.DataFrame:
    """上櫃個股日成交,欄位同 fetch_twse_daily。"""
    rows = _load(f"{TPEX}/tpex_mainboard_daily_close_quotes", "上櫃行情", "tpex_daily.json")
    return _daily_df(rows, ["SecuritiesCompanyCode", "代號"], ["CompanyName", "名稱"],
                     ["Close", "收盤"], ["Change", "漲跌"],
                     ["TransactionAmount", "成交金額", "TradingAmount"],
                     ["High", "最高"], ["Date", "日期"])


def fetch_capital_map() -> pd.DataFrame:
    """上市 t187ap03_L + 上櫃 t187ap03_O → code, capital(實收資本額,估市值用)。"""
    rows = []
    rows += _load(f"{TWSE}/opendata/t187ap03_L", "上市基本資料", "t187ap03_L.json")
    rows += _load(f"{TPEX}/mopsfin_t187ap03_O", "上櫃基本資料", "t187ap03_O.json")
    out = []
    for r in rows:
        code = str(_pick(r, "公司代號", "Code") or "").strip()
        if not code:
            continue
        out.append({"code": code,
                    "capital": _num(_pick(r, "實收資本額", "Capital")) or 0.0})
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
    """三大法人個股買賣超股數(上市 T86 + 上櫃)→ code, inst_net_shares。"""
    date8 = dt.date.today().strftime("%Y%m%d")
    payload = _load(f"{TWSE_RWD}/fund/T86?response=json&date={date8}&selectType=ALL",
                    "三大法人(上市)", "t86.json")
    twse_rows = _rwd_rows(payload)
    if not twse_rows:
        # T86 約 16:30 後發布;尚未發布或休市時視為來源暫缺,交由上層 fallback
        raise FetchError("三大法人(上市)", ValueError("T86 無當日資料"))
    tpex_rows = _load(f"{TPEX}/tpex_3insti_daily_trading", "三大法人(上櫃)", "tpex_inst.json")
    a = _inst_df(twse_rows, ["Code", "證券代號"],
                 ["TotalDifference", "三大法人買賣超股數", "Total"])
    b = _inst_df(tpex_rows, ["SecuritiesCompanyCode", "Code", "代號"],
                 ["TotalDifference", "三大法人買賣超股數合計", "三大法人買賣超股數", "Total"])
    return pd.concat([a, b], ignore_index=True)


IC_HOME = "https://ic.tpex.org.tw/"
CHAIN_CACHE_DAYS = 7
CHAIN_SECTION_PAT = re.compile(r"(本國上市|本國上櫃|本國興櫃|外國|僑外)")


def _get_text(url: str, source: str) -> str:
    last = None
    for attempt in range(RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            # ic.tpex 回應標頭未宣告 charset,requests 會誤用 Latin-1;頁面實為 UTF-8
            return resp.content.decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001 - 重試後統一包裝為 FetchError
            last = e
            if attempt < RETRIES - 1:
                time.sleep(RETRY_WAIT)
    raise FetchError(source, last)


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
    # (頁內每表出現兩次:圖示區視窗內無標題會自動跳過,清單區才解析)
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


def _crawl_chain_groups() -> pd.DataFrame:
    """爬全部產業鏈頁 → DataFrame[code, group];跨鏈同名族群加「鏈名-」前綴消歧。"""
    home = _get_text(IC_HOME, "產業分類")
    # 鏈代碼有英文字首(D000)與純數字(4100 太空衛星科技等前瞻科技類)兩種
    chains = sorted(set(re.findall(r"ic=([A-Z0-9][0-9]{3})", home)))
    if not chains:
        raise FetchError("產業分類", ValueError("首頁無產業鏈代碼"))
    by_group: dict = {}      # group -> {chain_name: set(codes)}
    chain_members: dict = {}  # chain_name -> set(codes)
    for ic in chains:
        page = _get_text(f"{IC_HOME}introduce.php?ic={ic}", f"產業分類({ic})")
        chain_name = parse_chain_name(page) or ic
        pairs = parse_chain_page(page)
        for group, code in pairs:
            by_group.setdefault(group, {}).setdefault(chain_name, set()).add(code)
        chain_members.setdefault(chain_name, set()).update(c for _, c in pairs)
        time.sleep(0.5)  # 禮貌間隔
    rows = []
    for group, chains_map in by_group.items():
        ambiguous = len(chains_map) > 1
        for chain_name, codes in chains_map.items():
            name = f"{chain_name}-{group}" if ambiguous else group
            rows.extend({"code": c, "group": name} for c in codes)
    # 鏈層級題材族群(「半導體」「太空衛星科技」整條鏈)
    for chain_name, codes in chain_members.items():
        rows.extend({"code": c, "group": chain_name} for c in codes)
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


def fetch_indices():
    """yfinance 近60日收盤;個別指數失敗不阻斷,回傳 (dict[symbol→Series], failed)。"""
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
