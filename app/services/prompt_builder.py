from __future__ import annotations


SYSTEM_PROMPT = """你是一个简洁、准确的内容解释助手。
根据原文本身判断场景，不要预设它是代码、报错或学习材料。
优先说明核心意思，并解释影响理解的术语；除非用户明确询问，否则不要主动给操作步骤或学习建议。
如果提供了“学习上下文”，解释必须优先结合其中的领域、场景和背景要点。
只输出 JSON，不要输出 Markdown。"""


def render_context_block(
    domain: str = "通用",
    scene: str = "通用",
    summary: str = "",
    instruction: str = "",
) -> str:
    parts: list[str] = []
    if domain and domain not in ("通用", "其他"):
        parts.append(f"领域：{domain}")
    if scene and scene not in ("通用", "其他"):
        parts.append(f"场景：{scene}")
    if summary.strip():
        parts.append(f"背景要点：{summary.strip()}")
    if instruction.strip():
        parts.append(instruction.strip())
    return "\n".join(parts)


def _context_prefix(context_block: str) -> str:
    block = (context_block or "").strip()
    if not block:
        return ""
    return f"学习上下文：\n{block}\n\n"


def build_user_prompt(source_text: str, mode: str = "default", context_block: str = "") -> str:
    mode_instruction = {
        "default": "用自然中文简洁说明核心意思。",
        "simple": "用更简单的中文说明，避免用新术语解释旧术语。",
        "examples": "简洁说明核心意思；确有帮助时补充 1 个短例子。",
    }.get(mode, "用自然中文简洁说明核心意思。")

    return f"""{_context_prefix(context_block)}简洁解释下面的内容原文。

规则：
1. explanation 用少量短句说明整体意思和必要上下文；术语细节统一放进 terms。即使 explanation 简短提到了某个概念，只要它是原文中独立的专业词、功能概念或陌生短语，仍必须进入 terms，不能因为正文提到过就省略。
2. 不写“这段内容是”等机械开头，不把所有场景都解释成报错或操作教程。
3. 原文为自然语言的句子或短语时给出自然的 translation；原文是代码、命令、配置文件或日志堆栈等不适合逐行翻译的内容时，translation 必须留空；原文已经是中文则留空。翻译只做简短直译：单词或缩写只给简短中文名（如 LSP→语言服务器协议），不要展开解释，展开内容放 explanation 或 terms。
4. terms 必须完整覆盖原文中所有影响理解的专业词、缩写、产品功能概念或陌生复合短语；没有这类概念时才返回空数组。原文是用顿号、逗号、分号、换行或项目符号列出的概念清单时，必须逐项检查，每个独立概念分别生成一条 term；同一项中用“与 / 和”连接两个独立概念时也要拆开。不要只挑最经典或最核心的两三个词。例如“缓存、重试幂等、来源回看”应返回 3 条，而不是只返回“幂等”。不要提取纯功能词（如 the、的、因为）。
5. 输出前逐项对照原文做一次覆盖检查，确认没有遗漏独立概念。每个术语用 1～2 句给出清楚、易懂的解释；例子确有助于理解时才提供，避免单项过长挤占其他术语。
6. learning_tip 仅在确有补充价值时填写，否则留空；确有关联概念值得延伸了解时，可在其中给出一条“延伸概念：概念名——一句话理由”的建议，帮助用户拓展学习思维。
7. tags 用于内容分类，保持简短。
8. 控制篇幅：原文只是一个词或短语时，explanation 不超过 2 句话；整体 explanation 一般不超过 3 句，除非原文本身很长。篇幅控制只能压缩 explanation 和单项解释，不能通过减少 terms 数量来省略原文概念。
9. 返回以下 JSON 结构；字段内容根据场景自然展开：

{{
  "explanation": "简短的核心解释",
  "translation": "必要时的简短中文翻译，否则为空字符串",
  "terms": [
    {{
      "term": "原文术语",
      "chinese_name": "简短中文名；原文术语已经是中文且没有不同的规范名称时必须为空字符串",
      "beginner_explanation": "清楚易懂的解释",
      "examples": ["可选例子"],
      "domain": "术语所属领域（可选，缺省视为当前学习方向）"
    }}
  ],
  "tags": ["标签"],
  "learning_tip": "可选补充，否则为空字符串"
}}

解释风格：
{mode_instruction}

原文：
{source_text.strip()}
"""


def build_followup_prompt(
    source_text: str,
    question: str,
    history: list[dict[str, str]] | None = None,
    mode: str = "custom",
    context_block: str = "",
) -> str:
    mode_instruction = {
        "simple": "用更简单的中文直接回答。",
        "examples": "直接回答；确有帮助时补充 1 个短例子。",
        "default": "重新简洁回答核心问题。",
        "custom": "按用户追问直接回答；用户要求详细时展开详细解释，不主动扩展无关内容。",
    }.get(mode, "按用户追问直接回答；用户要求详细时展开详细解释，不主动扩展无关内容。")

    history_lines: list[str] = []
    for item in history or []:
        role = item.get("role", "")
        content = item.get("content", "")
        if content:
            history_lines.append(f"{role}: {content[:1000]}")

    return f"""{_context_prefix(context_block)}结合原文和已有问答，简洁回答用户追问。

规则：
1. explanation 直接回答用户追问；用户明确要求更详细时展开详细解释（可多句、多步骤），否则保持简短。术语细节统一放进 terms；正文提到过的独立术语仍要进入 terms，不能借“避免复述”省略术语。
2. 仅当原文是自然语言且用户询问翻译或翻译有助于回答时填写 translation；代码、命令、配置等不翻译。
3. terms 必须完整覆盖原文和回答中所有影响理解的专业词、缩写、产品功能概念或陌生复合短语；清单内容要逐项提取，用“与 / 和”连接的独立概念要拆开，不要只挑两三个核心词。不要提取纯功能词（如 the、的、因为）；没有术语时才返回空数组。提供了“学习上下文”时按其中领域的口径解释。
4. 输出前逐项检查术语覆盖；每项解释保持 1～2 句，例子确有帮助时才提供。
5. learning_tip 仅在确有补充价值时填写，否则留空；确有关联概念值得延伸了解时，可给出一条“延伸概念：概念名——一句话理由”的建议。
6. 控制篇幅：默认 explanation 不超过 3 句；若用户追问中明确要求更详细、深入、展开或举例，则按用户要求详细回答，不受 3 句限制，也不要机械地省略必要细节。
7. 返回以下 JSON 结构；字段内容根据追问自然展开：

{{
  "explanation": "简短直接的回答",
  "translation": "必要时的翻译，否则为空字符串",
  "terms": [
    {{
      "term": "关键词或术语",
      "chinese_name": "简短中文名；原文术语已经是中文且没有不同的规范名称时必须为空字符串",
      "beginner_explanation": "清楚易懂的解释",
      "examples": ["可选例子"],
      "domain": "术语所属领域（可选）"
    }}
  ],
  "tags": ["标签"],
  "learning_tip": "可选补充，否则为空字符串"
}}

回答风格：
{mode_instruction}

原文：
{source_text.strip()}

已有问答：
{chr(10).join(history_lines) if history_lines else "无"}

用户追问：
{question.strip()}
"""
