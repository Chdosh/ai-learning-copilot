from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Generator

from app.services.prompt_builder import SYSTEM_PROMPT, build_followup_prompt, build_user_prompt
from app.services.settings import AppSettings


SUMMARY_SYSTEM_PROMPT = """你是一个文本压缩助手。把用户提供的原文压缩成"背景要点"，作为解释助手理解领域的锚点。
要求：中文输出；保留关键术语、专业名词、方法或核心结论；不要评价原文，不要复述原文结构，不要输出 Markdown。"""


class AIClientError(RuntimeError):
    pass


@dataclass(slots=True)
class TermExplanation:
    term: str
    chinese_name: str = ""
    beginner_explanation: str = ""
    examples: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AIResult:
    translation: str = ""
    explanation: str = ""
    terms: list[TermExplanation] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    learning_tip: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)


class AIClient:
    def __init__(self, settings: AppSettings, timeout_seconds: int = 60) -> None:
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    def explain_text(self, source_text: str, mode: str = "default") -> AIResult:
        if not source_text.strip():
            raise AIClientError("没有可解释的 OCR 文本。")
        if not self.settings.api_key.strip():
            raise AIClientError("未配置 API Key。请在设置页或 OPENAI_API_KEY 环境变量中填写。")

        payload = self._build_payload(source_text=source_text, mode=mode, include_response_format=True)
        try:
            response = self._post_chat(payload)
        except AIClientError as exc:
            if "response_format" not in str(exc):
                raise
            payload = self._build_payload(source_text=source_text, mode=mode, include_response_format=False)
            response = self._post_chat(payload)

        content = self._extract_content(response)
        parsed = parse_json_object(content)
        return parse_ai_result(parsed, raw_response=response)

    def stream_explain(self, source_text: str, mode: str = "default") -> Generator[str, None, None]:
        """Stream the structured JSON response as raw text deltas."""
        if not source_text.strip():
            raise AIClientError("没有可解释的 OCR 文本。")
        if not self.settings.api_key.strip():
            raise AIClientError("未配置 API Key。请在设置页或 OPENAI_API_KEY 环境变量中填写。")

        payload = self._build_payload(source_text=source_text, mode=mode, include_response_format=False)
        payload["stream"] = True
        yield from self._stream_request(payload)

    def stream_followup(
        self,
        source_text: str,
        question: str,
        history: list[dict[str, str]] | None = None,
        mode: str = "custom",
    ) -> Generator[str, None, None]:
        """Stream a follow-up answer as raw text deltas."""
        if not source_text.strip():
            raise AIClientError("没有可追问的 OCR 文本。")
        if not question.strip():
            raise AIClientError("追问内容不能为空。")
        if not self.settings.api_key.strip():
            raise AIClientError("未配置 API Key。请在设置页或 OPENAI_API_KEY 环境变量中填写。")

        payload = self._build_followup_payload(
            source_text=source_text,
            question=question,
            history=history,
            mode=mode,
        )
        yield from self._stream_request(payload)

    def _build_followup_payload(
        self,
        source_text: str,
        question: str,
        history: list[dict[str, str]] | None = None,
        mode: str = "custom",
    ) -> dict[str, Any]:
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_followup_prompt(
                        source_text=source_text,
                        question=question,
                        history=history,
                        mode=mode,
                        context_block=self.settings.context_block,
                    ),
                },
            ],
            "temperature": 0.2,
            "stream": True,
        }
        self._disable_deepseek_thinking(payload)
        return payload

    def _stream_request(self, payload: dict[str, Any]) -> Generator[str, None, None]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._chat_url(),
            data=data,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        return
                    try:
                        obj = json.loads(chunk)
                        delta = obj.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AIClientError(f"AI API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AIClientError(f"无法连接 AI API: {exc.reason}") from exc

    def _build_payload(self, source_text: str, mode: str, include_response_format: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_user_prompt(
                        source_text,
                        mode=mode,
                        context_block=self.settings.context_block,
                    ),
                },
            ],
            "temperature": 0.2,
        }
        if include_response_format:
            payload["response_format"] = {"type": "json_object"}
        self._disable_deepseek_thinking(payload)
        return payload

    def generate_summary(self, source_text: str, max_chars: int = 400) -> str:
        """Compress pasted text into a background-summary anchor (best effort).

        Returns an empty string on any failure so the caller can fall back to
        keyword-based suggestions instead of blocking context creation.
        """
        if not source_text.strip():
            return ""
        if not self.settings.api_key.strip():
            return ""
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"请把下面的内容压缩成背景要点（约 {max_chars} 字以内），保留关键术语。\n\n{source_text.strip()}",
                },
            ],
            "temperature": 0.2,
        }
        self._disable_deepseek_thinking(payload)
        try:
            response = self._post_chat(payload)
        except AIClientError:
            return ""
        content = self._extract_content(response).strip()
        if "```" in content:
            content = re.sub(
                r"^```(?:text)?\s*|\s*```$", "", content, flags=re.MULTILINE
            ).strip()
        if len(content) > max_chars * 3:
            return content[:max_chars]
        return content

    def _disable_deepseek_thinking(self, payload: dict[str, Any]) -> None:
        base_url = self.settings.base_url.casefold()
        model = self.settings.model.casefold()
        if "api.deepseek.com" in base_url and model.startswith("deepseek-v4"):
            payload["thinking"] = {"type": "disabled"}

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._chat_url(),
            data=data,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AIClientError(f"AI API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AIClientError(f"无法连接 AI API: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise AIClientError("AI API 返回的不是合法 JSON。") from exc

    def _chat_url(self) -> str:
        base_url = self.settings.base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    @staticmethod
    def _extract_content(response: dict[str, Any]) -> str:
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIClientError("AI API 返回结构不符合 Chat Completions 格式。") from exc


def parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError as fallback_exc:
                raise AIClientError("AI 返回内容不是合法 JSON。") from fallback_exc
        raise AIClientError("AI 返回内容不是合法 JSON。") from exc
    if not isinstance(value, dict):
        raise AIClientError("AI 返回 JSON 不是对象。")
    return value


def extract_stream_sections(content: str) -> dict[str, str | None]:
    """Extract monotonically growing visible fields from partial JSON."""
    translation = _extract_partial_json_string(content, "translation")
    explanation = _extract_partial_json_string(content, "explanation")
    learning_tip = _extract_partial_json_string(content, "learning_tip")
    return {
        "translation": (
            compact_line_breaks(translation) if translation is not None else None
        ),
        "explanation": (
            compact_line_breaks(explanation) if explanation is not None else None
        ),
        "learning_tip": (
            compact_line_breaks(learning_tip) if learning_tip is not None else None
        ),
    }


def compact_line_breaks(text: str) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n[ \t]*\n+", "\n", normalized).strip()


def extract_stream_terms(content: str) -> list[dict]:
    """Extract fully-closed term objects from partial JSON content."""
    match = re.search(r'"terms"\s*:\s*\[', content)
    if match is None:
        return []
    tail = content[match.end():]
    terms: list[dict] = []
    search_pos = 0
    while True:
        start = tail.find("{", search_pos)
        if start < 0:
            break
        end = start
        depth = 0
        in_string = False
        escaped = False
        while end < len(tail):
            char = tail[end]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        break
            end += 1
        if depth != 0:
            break
        try:
            obj = json.loads(tail[start : end + 1])
        except json.JSONDecodeError:
            search_pos = start + 1
            continue
        if isinstance(obj, dict) and str(obj.get("term") or "").strip():
            terms.append(obj)
        search_pos = end + 1
    return terms


def _extract_partial_json_string(content: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"', content)
    if match is None:
        return None

    output: list[str] = []
    index = match.end()
    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
    while index < len(content):
        char = content[index]
        if char == '"':
            break
        if ord(char) != 92:
            output.append(char)
            index += 1
            continue
        if index + 1 >= len(content):
            break
        escaped = content[index + 1]
        if escaped == "u":
            digits = content[index + 2 : index + 6]
            if len(digits) < 4 or any(ch not in "0123456789abcdefABCDEF" for ch in digits):
                break
            output.append(chr(int(digits, 16)))
            index += 6
            continue
        output.append(escapes.get(escaped, escaped))
        index += 2
    return "".join(output)


def parse_ai_result(value: dict[str, Any], raw_response: dict[str, Any] | None = None) -> AIResult:
    terms: list[TermExplanation] = []
    raw_terms = value.get("terms")
    if not isinstance(raw_terms, list):
        raw_terms = []
    for item in raw_terms:
        if not isinstance(item, dict):
            continue
        examples = item.get("examples")
        if not isinstance(examples, list):
            examples = []
        terms.append(
            TermExplanation(
                term=str(item.get("term") or "").strip(),
                chinese_name=str(item.get("chinese_name") or "").strip(),
                beginner_explanation=str(
                    item.get("beginner_explanation") or ""
                ).strip(),
                examples=[str(example).strip() for example in examples if str(example).strip()],
            )
        )
    tags = value.get("tags")
    if not isinstance(tags, list):
        tags = []
    return AIResult(
        translation=compact_line_breaks(str(value.get("translation") or "")),
        explanation=compact_line_breaks(str(value.get("explanation") or "")),
        terms=[term for term in terms if term.term],
        tags=[str(tag).strip() for tag in tags if str(tag).strip()],
        learning_tip=compact_line_breaks(str(value.get("learning_tip") or "")),
        raw_response=raw_response or {},
    )
