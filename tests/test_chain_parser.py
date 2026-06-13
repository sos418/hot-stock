from pathlib import Path

import fetchers

HTML = (Path(__file__).parent / "fixtures/chain_sample.html").read_text(encoding="utf-8")


def test_parse_chain_name():
    assert fetchers.parse_chain_name(HTML) == "測試"


def test_parse_chain_page_levels_and_dedupe():
    triples = fetchers.parse_chain_page(HTML)
    assert ("sub", "細分 X", "1111") in triples     # 細分類(sc_company 表)
    assert ("main", "主分A", "3333") in triples      # 主分類(companyList)
    assert ("main", "主分B", "4444") in triples
    assert not any(g == "本國上市公司" for _, g, _ in triples)  # 章節標籤不可當族群
    assert len([t for t in triples if t[1] == "細分 X"]) == 2   # 重複表格已去重
