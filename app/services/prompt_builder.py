from __future__ import annotations


SYSTEM_PROMPT = """你是一个耐心、准确的 AI 学习助手，服务对象是英语和计算机基础较弱的初学者。
你的任务不是直译，而是帮助用户快速看懂英文软件界面、报错、AI/编程术语。
只输出 JSON，不要输出 Markdown。"""


def build_user_prompt(source_text: str, mode: str = "default") -> str:
    mode_instruction = {
        "default": "用小白能懂的中文解释，保持准确、简洁。",
        "simple": "把解释降到更基础的程度，少用术语，多用生活化类比。",
        "examples": "重点给出 2-3 个使用场景或例子，帮助用户建立直觉。",
    }.get(mode, "用小白能懂的中文解释，保持准确、简洁。")

    return f"""请分析下面这段从截图 OCR 得到的内容。

要求：
1. 翻译成自然中文，不要机械逐词翻译。
2. 如果包含计算机、AI、编程、软件界面或报错术语，提取为 terms。
3. explanation 面向基础很差的新手，解释它在当前语境里是什么意思。
4. tags 给出 1-5 个短标签，例如 AI、Python、报错、软件界面、网络、数据库。
5. 输出必须是合法 JSON，对象结构固定如下：

{{
  "translation": "中文翻译",
  "explanation": "小白解释",
  "terms": [
    {{
      "term": "英文术语",
      "chinese_name": "中文名",
      "beginner_explanation": "小白解释",
      "examples": ["例子 1", "例子 2"]
    }}
  ],
  "tags": ["标签1", "标签2"],
  "learning_tip": "一句学习建议"
}}

解释风格：
{mode_instruction}

OCR 原文：
{source_text.strip()}
"""


def build_followup_prompt(
    source_text: str,
    question: str,
    history: list[dict[str, str]] | None = None,
    mode: str = "custom",
) -> str:
    mode_instruction = {
        "simple": "请把解释变得更简单，少用术语，多用生活化类比。",
        "examples": "请重点举 2-3 个具体例子，帮助用户理解。",
        "default": "请重新解释，保持准确、简洁。",
        "custom": "请直接回答用户追问，必要时结合上下文解释术语。",
    }.get(mode, "请直接回答用户追问，必要时结合上下文解释术语。")

    history_lines: list[str] = []
    for item in history or []:
        role = item.get("role", "")
        content = item.get("content", "")
        if content:
            history_lines.append(f"{role}: {content[:1000]}")

    return f"""这是同一张截图下的后续追问。请结合 OCR 原文和已有问答回答。

输出仍然必须是合法 JSON，对象结构固定如下：

{{
  "translation": "如果问题涉及翻译，给出中文翻译；否则可以留空",
  "explanation": "回答用户追问，面向基础较弱的新手",
  "terms": [
    {{
      "term": "关键词或术语",
      "chinese_name": "中文名",
      "beginner_explanation": "小白解释",
      "examples": ["例子 1", "例子 2"]
    }}
  ],
  "tags": ["标签1", "标签2"],
  "learning_tip": "一句学习建议"
}}

回答风格：
{mode_instruction}

OCR 原文：
{source_text.strip()}

已有问答：
{chr(10).join(history_lines) if history_lines else "无"}

用户追问：
{question.strip()}
"""
