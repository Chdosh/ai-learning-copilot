from app.services.ai_client import parse_ai_result, parse_json_object
from app.services.prompt_builder import build_user_prompt


def test_build_user_prompt_contains_source_text() -> None:
    prompt = build_user_prompt("Token limit exceeded.", mode="simple")

    assert "Token limit exceeded." in prompt
    assert '"translation"' in prompt
    assert '"terms"' in prompt


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
    assert result.tags == ["AI", "报错"]
