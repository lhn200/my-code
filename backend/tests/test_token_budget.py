from app.memory.token_budget import count_tokens


def test_empty_text_counts_zero() -> None:
    assert count_tokens("") == 0


def test_non_empty_text_counts_positive() -> None:
    assert count_tokens("hello world") > 0


def test_chinese_costs_more_than_same_length_ascii() -> None:
    chinese = "数据分析方向"
    ascii_text = "a" * len(chinese)
    assert count_tokens(chinese) > count_tokens(ascii_text)


def test_count_is_stable() -> None:
    text = "半年度内转向数据方向，目前在职，只能线上面试。"
    assert count_tokens(text) == count_tokens(text)
