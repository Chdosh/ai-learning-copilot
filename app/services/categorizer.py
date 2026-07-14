from __future__ import annotations

import re
from typing import Optional


CATEGORIES = ["报错", "AI概念", "Python", "数据库", "网络", "文档", "其他"]

_CATEGORY_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "报错": [
        re.compile(r"error|exception|traceback|failed|failure|crash|bug|abort|refused|timeout|unhandled|panic|denied|invalid|not found|forbidden", re.IGNORECASE),
        re.compile(r"报错|异常|错误|失败|崩溃|超时|拒绝|未找到|不允许"),
    ],
    "AI概念": [
        re.compile(r"\bAI\b|machine learning|deep learning|neural|model|training|inference|LLM|GPT|transformer|embedding|token|prompt|fine-tun|RLHF|agent|diffusion|generative", re.IGNORECASE),
        re.compile(r"人工智能|机器学习|深度学习|神经网络|模型|训练|推理|大语言|向量|提示词|智能体"),
    ],
    "Python": [
        re.compile(r"\bpython\b|\.py\b|import\s|def\s|class\s.*:|pip\s|virtualenv|conda|pytest|flask|django|fastapi|pandas|numpy", re.IGNORECASE),
        re.compile(r"python|蟒蛇|pip|包管理|虚拟环境|装饰器|生成器|迭代器"),
    ],
    "数据库": [
        re.compile(r"\bsql\b|database|mysql|postgres|mongodb|redis|sqlite|query|schema|migration|index|join|transaction|NoSQL|ORM", re.IGNORECASE),
        re.compile(r"数据库|查询|表|索引|事务|SQL|关系型|非关系型|缓存"),
    ],
    "网络": [
        re.compile(r"http|tcp|udp|ip\b|socket|dns|cdn|proxy|firewall|port\b|request|response|REST|API|grpc|websocket|ssl|tls|vpn|load.?balanc", re.IGNORECASE),
        re.compile(r"网络|请求|响应|接口|协议|端口|代理|防火墙|网关|负载均衡"),
    ],
    "文档": [
        re.compile(r"README|documentation|docs|manual|guide|tutorial|changelog|license|copyright|version|install|setup|config", re.IGNORECASE),
        re.compile(r"文档|手册|指南|教程|安装|配置|版本|许可证|说明"),
    ],
}

_CATEGORY_TAG_MAP: dict[str, str] = {
    "报错": "报错",
    "error": "报错",
    "exception": "报错",
    "AI": "AI概念",
    "AI概念": "AI概念",
    "LLM": "AI概念",
    "Python": "Python",
    "数据库": "数据库",
    "SQL": "数据库",
    "网络": "网络",
    "HTTP": "网络",
    "API": "网络",
    "文档": "文档",
    "README": "文档",
}


def auto_categorize(source_text: str, tags: list[str]) -> str:
    for tag in tags:
        if tag in _CATEGORY_TAG_MAP:
            return _CATEGORY_TAG_MAP[tag]

    text = source_text.strip()
    if not text:
        return ""

    scores: dict[str, int] = {}
    for category, patterns in _CATEGORY_PATTERNS.items():
        score = 0
        for pattern in patterns:
            matches = pattern.findall(text)
            score += len(matches)
        if score > 0:
            scores[category] = score

    if not scores:
        return ""

    return max(scores, key=scores.get)  # type: ignore[return-value]


def get_all_categories() -> list[str]:
    return list(CATEGORIES)


def is_valid_category(category: str) -> bool:
    return category in CATEGORIES
