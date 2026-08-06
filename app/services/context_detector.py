"""Lightweight domain / scene / keyword detection for learning contexts.

Used only to *suggest* a learning context when the user pastes longer text
(e.g. a paper abstract). Single-word inputs never go through detection.
"""
from __future__ import annotations

import re
from collections import Counter

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "编程": [
        "代码", "函数", "变量", "编译", "接口", "报错", "bug", "error", "exception",
        "python", "java", "javascript", "sql", "api", "class", "function",
        "server", "database", "框架", "部署",
    ],
    "生物": [
        "细胞", "基因", "dna", "rna", "蛋白质", "蛋白", "酶", "遗传", "转录",
        "染色体", "生物", "进化", "organism", "gene", "cell", "protein",
        "基因组", "序列", "突变",
    ],
    "医学": [
        "患者", "疾病", "药物", "治疗", "临床", "症状", "诊断", "手术", "医院",
        "肿瘤", "感染", "patient", "disease", "clinical", "therapy",
    ],
    "法律": [
        "条款", "法律", "合同", "法规", "判决", "原告", "被告", "法条", "诉讼",
        "产权", "侵权", "law", "contract", "clause", "legal",
    ],
    "金融": [
        "股票", "利率", "投资", "基金", "债券", "gdp", "市场", "汇率", "股市",
        "估值", "收益", "stock", "market", "finance", "investment",
    ],
    "物理": [
        "粒子", "量子", "能量", "波", "电场", "磁场", "力学", "相对论", "光子",
        "physics", "quantum", "electron", "重力",
    ],
    "化学": [
        "分子", "化学", "反应", "化合物", "原子", "ph", "催化剂", "离子",
        "chemistry", "molecule", "reaction",
    ],
    "数学": [
        "方程", "函数", "概率", "矩阵", "积分", "几何", "定理", "算法", "微分",
        "math", "equation", "matrix", "probability",
    ],
    "社科": [
        "社会", "经济", "政治", "文化", "历史", "心理", "哲学", "教育", "政策",
        "society", "culture", "psychology", "policy",
    ],
}

SCENE_KEYWORDS: dict[str, list[str]] = {
    "学术论文": [
        "摘要", "研究", "实验", "结果", "结论", "文献", "参考文献", "方法", "样本",
        "abstract", "research", "study", "experiment", "method", "results",
        "discussion", "doi",
    ],
    "报错信息": [
        "error", "exception", "failed", "traceback", "warning", "错误", "无法",
        "失败", "报错", "invalid", "not found",
    ],
    "技术文档": [
        "文档", "说明", "配置", "安装", "使用", "手册", "api", "reference",
        "documentation", "setup", "guide", "教程",
    ],
    "软件界面": [
        "设置", "选项", "按钮", "点击", "菜单", "登录", "保存", "取消", "提示",
        "settings", "option", "button", "menu", "login",
    ],
    "新闻资讯": [
        "报道", "新闻", "记者", "发布", "声明", "据悉", "据", "新闻社",
        "news", "report", "announced",
    ],
}

_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "this", "that", "with", "as", "by", "at", "from", "be", "it", "its", "we",
    "our", "you", "your", "he", "she", "they", "them", "his", "her", "their",
    "about", "between", "into", "through", "during", "after", "before", "not",
    "have", "has", "had", "was", "were", "been", "being", "do", "does", "did",
    "can", "could", "will", "would", "should", "may", "might", "must", "which",
    "who", "whom", "whose", "when", "where", "why", "how", "than", "then",
    "also", "over", "under", "more", "most", "such", "some", "any", "each",
    "both", "only", "very", "just", "still", "even", "well", "many", "much",
    "的", "了", "是", "在", "和", "有", "与", "也", "就", "都", "而", "及", "或",
    "一个", "我们", "你们", "他们", "这个", "那个", "这些", "那些", "通过", "关于",
    "对于", "以及", "并且", "所以", "因为", "但是", "如果", "可以", "能够", "进行",
    "使用", "其中", "本文", "该文",
}


_ASCII_KEYWORD = re.compile(r"^[A-Za-z0-9_]+$")
_KEYWORD_PATTERNS: dict[str, re.Pattern[str]] = {}


def _keyword_matches(text: str, keyword: str) -> bool:
    """Match English keywords on word boundaries, Chinese as plain substring."""
    pattern = _KEYWORD_PATTERNS.get(keyword)
    if pattern is None:
        if _ASCII_KEYWORD.match(keyword):
            pattern = re.compile(rf"\b{re.escape(keyword)}\b")
        else:
            pattern = re.compile(re.escape(keyword))
        _KEYWORD_PATTERNS[keyword] = pattern
    return pattern.search(text) is not None


def _score(text: str, keywords: list[str]) -> int:
    lowered = text.casefold()
    return sum(1 for keyword in keywords if _keyword_matches(lowered, keyword))


def detect_domain(text: str) -> str:
    """Return the most likely domain keyword, or '其他'."""
    if not text or not text.strip():
        return "其他"
    best = "其他"
    best_score = 0
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = _score(text, keywords)
        if score > best_score:
            best, best_score = domain, score
    return best


def detect_scene(text: str) -> str:
    """Return the most likely scene keyword, or '通用'."""
    if not text or not text.strip():
        return "通用"
    best = "通用"
    best_score = 0
    for scene, keywords in SCENE_KEYWORDS.items():
        score = _score(text, keywords)
        if score > best_score:
            best, best_score = scene, score
    return best


def detect(text: str) -> dict[str, str]:
    return {
        "domain": detect_domain(text),
        "scene": detect_scene(text),
    }


MIN_SUGGEST_LENGTH = 120


def suggest_context(text: str) -> dict[str, object]:
    """Suggest a learning context for a pasted longer text (suggestion only).

    ``recommended`` is True only when the text is long enough and carries some
    domain/scene signal, so short pastes and word-level input never trigger it.
    """
    stripped = (text or "").strip()
    domain = detect_domain(stripped)
    scene = detect_scene(stripped)
    keywords = extract_keywords(stripped)
    recommended = len(stripped) >= MIN_SUGGEST_LENGTH and (
        domain != "其他" or scene != "通用"
    )
    return {
        "domain": domain,
        "scene": scene,
        "keywords": keywords,
        "recommended": recommended,
    }


def extract_keywords(text: str, limit: int = 8) -> list[str]:
    """Extract frequent domain-ish terms (English words + Chinese phrases).

    Chinese segmentation is not available, so Chinese tokens are split on
    punctuation/whitespace; a continuous run becomes one candidate. This is a
    suggestion-level extractor — the primary summary comes from the AI in UI.
    """
    if not text:
        return []
    tokens: list[str] = []
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_]*|[\u4e00-\u9fff]{2,}", text):
        raw = match.group(0)
        token = raw.casefold() if raw.isascii() else raw
        if token in _STOPWORDS:
            continue
        if raw.isascii() and len(raw) < 3:
            continue
        tokens.append(token)
    counts = Counter(tokens)
    return [token for token, _ in counts.most_common(limit)]
