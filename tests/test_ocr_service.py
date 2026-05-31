from app.services.ocr import _clean_text, _normalize_lang


def test_normalize_lang_aliases() -> None:
    assert _normalize_lang("en") == "eng"
    assert _normalize_lang("english") == "eng"
    assert _normalize_lang("zh-CN") == "chi_sim"
    assert _normalize_lang("mixed") == "eng+chi_sim"
    assert _normalize_lang("") == "eng+chi_sim"
    assert _normalize_lang("eng") == "eng"


def test_clean_text_removes_empty_and_duplicate_lines() -> None:
    text = _clean_text(" Hello   world \n\nhello world\nToken   limit ")

    assert text == "Hello world\nToken limit"
