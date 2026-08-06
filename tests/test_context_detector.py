from app.services.context_detector import (
    detect,
    detect_domain,
    detect_scene,
    extract_keywords,
    suggest_context,
)


def test_detect_domain_biology():
    text = "基因编辑技术在细胞培养中的应用，CRISPR 和 DNA 序列分析。"
    assert detect_domain(text) == "生物"


def test_detect_domain_programming():
    text = "python error: function not defined, exception in server API"
    assert detect_domain(text) == "编程"


def test_detect_domain_finance():
    text = "股票市场利率上升，投资基金的债券收益率变化。"
    assert detect_domain(text) == "金融"


def test_detect_domain_unknown():
    assert detect_domain("随便一句普通的话。") == "其他"
    assert detect_domain("") == "其他"


def test_detect_domain_english_keywords_use_word_boundaries():
    assert detect_domain("capital market, excellent portfolio returns") == "金融"
    assert detect_domain("cell biology study") == "生物"


def test_detect_scene_academic():
    text = "摘要：本研究通过实验得出结果，结论如下，参考文献见附录。"
    assert detect_scene(text) == "学术论文"


def test_detect_scene_error():
    text = "Error: failed to connect, exception thrown, invalid argument"
    assert detect_scene(text) == "报错信息"


def test_detect_returns_both():
    result = detect("细胞基因编辑实验摘要，参考文献与方法。")
    assert result["domain"] == "生物"
    assert result["scene"] == "学术论文"


def test_extract_keywords_english():
    words = extract_keywords(
        "CRISPR Cas9 gene editing in cells requires guide RNA and the Cas9 protein",
        limit=4,
    )
    assert "crispr" in words
    assert "cas9" in words
    assert "the" not in words


def test_extract_keywords_empty_and_short():
    assert extract_keywords("") == []
    assert extract_keywords("a b c") == []


def test_suggest_context_long_text_with_signal():
    text = (
        "本研究摘要：我们利用 CRISPR 对细胞进行了基因编辑实验，"
        "分析了 DNA 序列突变与蛋白质表达之间的关系，结果与结论见正文，参考文献见附录。" * 3
    )
    suggestion = suggest_context(text)
    assert suggestion["domain"] == "生物"
    assert suggestion["scene"] == "学术论文"
    assert suggestion["keywords"]
    assert suggestion["recommended"] is True


def test_suggest_context_short_text_not_recommended():
    suggestion = suggest_context("hello world")
    assert suggestion["recommended"] is False

    long_generic = "这是一段很长但没有领域信号的中文普通叙述。" * 5
    suggestion = suggest_context(long_generic)
    assert suggestion["recommended"] is False
