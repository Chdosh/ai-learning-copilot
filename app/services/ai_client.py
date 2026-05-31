from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from app.services.prompt_builder import SYSTEM_PROMPT, build_followup_prompt, build_user_prompt
from app.services.settings import AppSettings


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

    @classmethod
    def from_error(cls, message: str) -> "AIResult":
        return cls(
            translation="",
            explanation=message,
            terms=[],
            tags=["待处理"],
            learning_tip="请先检查 OCR 内容、API Key 和网络连接。",
        )


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

    def ask_followup(
        self,
        source_text: str,
        question: str,
        history: list[dict[str, str]] | None = None,
        mode: str = "custom",
    ) -> AIResult:
        if not source_text.strip():
            raise AIClientError("没有可追问的 OCR 文本。")
        if not question.strip():
            raise AIClientError("追问内容不能为空。")
        if not self.settings.api_key.strip():
            raise AIClientError("未配置 API Key。请在设置页或 OPENAI_API_KEY 环境变量中填写。")

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
                    ),
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        try:
            response = self._post_chat(payload)
        except AIClientError as exc:
            if "response_format" not in str(exc):
                raise
            payload.pop("response_format", None)
            response = self._post_chat(payload)

        content = self._extract_content(response)
        parsed = parse_json_object(content)
        return parse_ai_result(parsed, raw_response=response)

    def _build_payload(self, source_text: str, mode: str, include_response_format: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(source_text, mode=mode)},
            ],
            "temperature": 0.2,
        }
        if include_response_format:
            payload["response_format"] = {"type": "json_object"}
        return payload

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


def parse_ai_result(value: dict[str, Any], raw_response: dict[str, Any] | None = None) -> AIResult:
    terms: list[TermExplanation] = []
    for item in value.get("terms") or []:
        if not isinstance(item, dict):
            continue
        examples = item.get("examples") or []
        terms.append(
            TermExplanation(
                term=str(item.get("term") or "").strip(),
                chinese_name=str(item.get("chinese_name") or "").strip(),
                beginner_explanation=str(item.get("beginner_explanation") or "").strip(),
                examples=[str(example) for example in examples if str(example).strip()],
            )
        )
    tags = value.get("tags") or []
    return AIResult(
        translation=str(value.get("translation") or "").strip(),
        explanation=str(value.get("explanation") or "").strip(),
        terms=[term for term in terms if term.term],
        tags=[str(tag).strip() for tag in tags if str(tag).strip()],
        learning_tip=str(value.get("learning_tip") or "").strip(),
        raw_response=raw_response or {},
    )
