"""术语数据治理：停用词兜底与难度分级（纯本地规则，零 API 成本）。

- 纯功能词（the / 的 / 因为 …）永远不是术语，AI 误提时直接跳过。
- 常见简单词（if / for / file …）是真实术语但价值低，标为 ``basic``，
  由列表层配合行为信号（收藏 / 查看 / 复习）折叠，绝不硬删除——
  ``if``、``for`` 对编程新手恰恰是需要学的词。
"""
from __future__ import annotations

PURE_STOPWORDS: frozenset[str] = frozenset({
    # 英语功能词
    "the", "a", "an", "of", "to", "in", "on", "and", "or", "is", "are",
    "was", "were", "be", "been", "being", "this", "that", "these", "those",
    "with", "as", "by", "at", "from", "it", "its", "we", "our", "you",
    "your", "he", "she", "they", "them", "his", "her", "their", "not",
    "have", "has", "had", "do", "does", "did", "can", "could", "will",
    "would", "should", "may", "might", "must", "which", "who", "whom",
    "whose", "when", "where", "why", "how", "than", "then", "also", "over",
    "under", "more", "most", "such", "some", "any", "each", "both", "only",
    "very", "just", "still", "even", "well", "many", "much", "about",
    "between", "into", "through", "during", "after", "before", "while",
    "what", "so", "no", "yes", "up", "down", "out", "off",
    # 汉语功能词 / 代词
    "的", "了", "是", "在", "和", "有", "与", "也", "就", "都", "而", "及",
    "或", "一个", "我们", "你们", "他们", "这个", "那个", "这些", "那些",
    "通过", "关于", "对于", "以及", "并且", "所以", "因为", "但是", "如果",
    "可以", "能够", "进行", "使用", "其中", "本文", "该文", "什么", "怎么",
    "如何", "为什么", "就是", "不是", "没有", "已经", "还是", "只是",
})

BASIC_WORDS: frozenset[str] = frozenset({
    # 编程关键字 / 常见词（对新手仍是学习对象，但默认折叠）
    "if", "for", "else", "elif", "while", "return", "import", "print",
    "class", "def", "file", "folder", "window", "button", "click", "save",
    "open", "close", "user", "data", "code", "app", "server", "client",
    "page", "link", "list", "string", "text", "image", "error", "warning",
    "run", "build", "install", "version", "name", "value", "key", "type",
    "table", "row", "column", "line", "word", "number", "start", "stop",
    "end", "check", "select", "delete", "update", "create", "new", "old",
    "main", "test", "file_path", "true", "false", "none", "null",
})


def is_pure_stopword(term: str) -> bool:
    """Return True when the term is a pure function word and never worth keeping."""
    return (term or "").strip().casefold() in PURE_STOPWORDS


def classify_difficulty(term: str) -> str:
    """Classify a term's difficulty with local rules; ``""`` = not evaluated."""
    if (term or "").strip().casefold() in BASIC_WORDS:
        return "basic"
    return ""
