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
