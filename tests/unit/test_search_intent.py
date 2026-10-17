from services.search.retrieval import query_intent


def test_extracts_english_document_and_page_intent():
    assert query_intent("Show the middle leaf in the ninth sample.") == (9, "middle")
    assert query_intent("Locate the opening leaf in the eleventh sample.") == (11, "first")


def test_extracts_chinese_document_and_page_intent():
    assert query_intent("打开第十份资料的最后一页") == (10, "last")
    assert query_intent("查看第十二份资料正中间的那一页") == (12, "middle")
    assert query_intent("找出第六份只有一页的资料") == (6, None)


def test_does_not_invent_a_number_or_page_hint():
    assert query_intent("find the recovery procedure") == (None, None)
