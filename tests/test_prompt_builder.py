from app.services.ai_client import AIClient, AIClientError, parse_ai_result, parse_json_object
from app.services.prompt_builder import (
    build_followup_prompt,
    build_user_prompt,
    render_context_block,
)
from app.services.settings import AppSettings


def test_build_user_prompt_contains_source_text() -> None:
    prompt = build_user_prompt("Token limit exceeded.", mode="simple")

    assert "Token limit exceeded." in prompt
    assert '"translation"' in prompt
    assert '"terms"' in prompt
    assert "terms 必须完整覆盖" in prompt
    assert '"learning_tip"' in prompt
    assert '"examples"' in prompt


def test_prompt_requires_list_items_to_be_covered_individually() -> None:
    prompt = build_user_prompt("即时出现、重试幂等、来源回看、关联理由、推荐排除与忽略持久化")

    assert "必须逐项检查" in prompt
    assert "每个独立概念分别生成一条 term" in prompt
    assert "与 / 和" in prompt
    assert "不能通过减少 terms 数量" in prompt
    assert "原文术语已经是中文" in prompt


def test_prompts_keep_terms_and_make_extra_advice_optional() -> None:
    prompt = build_followup_prompt(
        source_text="A technical term",
        question="这是什么意思？",
    )

    assert '"terms"' in prompt
    assert "terms 必须完整覆盖" in prompt
    assert '"learning_tip"' in prompt
    assert "仅在确有补充价值时填写" in prompt


def test_followup_prompt_allows_detail_when_requested() -> None:
    prompt = build_followup_prompt(
        source_text="A technical term",
        question="请详细解释，展开说明所有细节",
    )

    assert "用户明确要求更详细" in prompt
    assert "不受 3 句限制" in prompt


def test_ai_payload_does_not_hard_cap_output() -> None:
    client = AIClient(
        AppSettings(
            api_key="test",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1-mini",
        )
    )
    payload = client._build_payload("hello", mode="default", include_response_format=False)

    assert "max_tokens" not in payload
    assert payload["temperature"] == 0.2
    assert "thinking" not in payload


def test_deepseek_v4_payload_disables_default_thinking() -> None:
    client = AIClient(
        AppSettings(
            api_key="test",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
        )
    )

    payload = client._build_payload(
        "hello", mode="default", include_response_format=False
    )

    assert payload["thinking"] == {"type": "disabled"}


def test_parse_ai_result_from_fenced_json() -> None:
    parsed = parse_json_object(
        """```json
        {
          "translation": "超过 token 限制",
          "explanation": "内容太长。",
          "terms": [
            {
              "term": "token",
              "chinese_name": "文本单位",
              "beginner_explanation": "AI 读文字时的计量单位。",
              "examples": ["一个英文单词可能是一个或多个 token"]
            }
          ],
          "tags": ["AI", "报错"],
          "learning_tip": "分段发送内容。"
        }
        ```"""
    )
    result = parse_ai_result(parsed)

    assert result.translation == "超过 token 限制"
    assert result.terms[0].term == "token"
    assert result.terms[0].examples == ["一个英文单词可能是一个或多个 token"]
    assert result.tags == ["AI", "报错"]
    assert result.learning_tip == "分段发送内容。"


def test_parse_ai_result_preserves_complete_structure() -> None:
    result = parse_ai_result(
        {
            "explanation": "很长的解释" * 40,
            "translation": "",
            "terms": [
                {
                    "term": f"term-{index}",
                    "chinese_name": "术语",
                    "beginner_explanation": "解释" * 60,
                }
                for index in range(5)
            ],
            "tags": ["一", "二", "三"],
            "learning_tip": "不应进入首轮结果",
        }
    )

    assert result.explanation == "很长的解释" * 40
    assert len(result.terms) == 5
    assert all(term.beginner_explanation == "解释" * 60 for term in result.terms)
    assert result.tags == ["一", "二", "三"]
    assert result.learning_tip == "不应进入首轮结果"


def test_parse_ai_result_drops_duplicate_chinese_name() -> None:
    result = parse_ai_result(
        {
            "terms": [
                {
                    "term": "幂等",
                    "chinese_name": "幂等",
                    "beginner_explanation": "重复执行结果一致。",
                },
                {
                    "term": "Idempotency",
                    "chinese_name": "幂等性",
                    "beginner_explanation": "重复执行结果一致。",
                },
            ]
        }
    )

    assert result.terms[0].chinese_name == ""
    assert result.terms[1].chinese_name == "幂等性"


def test_render_context_block() -> None:
    block = render_context_block(
        domain="生物", scene="学术论文", summary="CRISPR 基因编辑", instruction="术语给中文对照"
    )
    assert "领域：生物" in block
    assert "场景：学术论文" in block
    assert "CRISPR 基因编辑" in block
    assert "术语给中文对照" in block


def test_render_context_block_generic_skips_defaults() -> None:
    assert render_context_block() == ""
    assert render_context_block(domain="通用", scene="通用") == ""


def test_build_user_prompt_includes_context_block() -> None:
    prompt = build_user_prompt(
        "CRISPR",
        context_block="领域：生物\n场景：学术论文\n背景要点：CRISPR 基因编辑",
    )
    assert "学习上下文：" in prompt
    assert "领域：生物" in prompt
    assert "背景要点：CRISPR 基因编辑" in prompt
    assert "CRISPR" in prompt


def test_build_user_prompt_without_context_block_unchanged() -> None:
    plain = build_user_prompt("hello")
    with_context = build_user_prompt("hello", context_block="")
    assert plain == with_context
    assert "学习上下文：" not in plain


def test_build_followup_prompt_includes_context_block() -> None:
    prompt = build_followup_prompt(
        "CRISPR",
        "这是什么？",
        context_block="领域：生物\n场景：学术论文",
    )
    assert "学习上下文：" in prompt
    assert "领域：生物" in prompt


def test_ai_payload_uses_context_block() -> None:
    client = AIClient(
        AppSettings(api_key="test", context_block="领域：生物\n场景：学术论文")
    )
    payload = client._build_payload("CRISPR", mode="default", include_response_format=False)
    user_content = payload["messages"][1]["content"]
    assert "领域：生物" in user_content
    assert "场景：学术论文" in user_content


def test_ai_followup_payload_uses_context_block() -> None:
    client = AIClient(
        AppSettings(api_key="test", context_block="领域：生物\n场景：学术论文")
    )
    payload = client._build_followup_payload("CRISPR", "这是什么？")
    assert payload["stream"] is True
    user_content = payload["messages"][1]["content"]
    assert "领域：生物" in user_content
    assert "场景：学术论文" in user_content


def test_generate_summary_returns_compressed_text(monkeypatch) -> None:
    client = AIClient(AppSettings(api_key="test"))

    def fake_post(payload):
        return {"choices": [{"message": {"content": "```text\nCRISPR 基因编辑的关键要点\n```"}}]}

    monkeypatch.setattr(client, "_post_chat", fake_post)
    summary = client.generate_summary("CRISPR 基因编辑实验内容" * 5)
    assert "基因编辑" in summary
    assert "```" not in summary


def test_generate_summary_returns_empty_on_error(monkeypatch) -> None:
    client = AIClient(AppSettings(api_key="test"))

    def fake_post(payload):
        raise AIClientError("network down")

    monkeypatch.setattr(client, "_post_chat", fake_post)
    assert client.generate_summary("some text") == ""


def test_generate_summary_requires_api_key() -> None:
    client = AIClient(AppSettings(api_key=""))
    assert client.generate_summary("some text") == ""
