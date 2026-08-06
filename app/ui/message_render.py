"""Shared HTML rendering for AI answers (popup + workbench)."""
from __future__ import annotations

import html
import re

from app.services.ai_client import compact_line_breaks


DOC_STYLESHEET = (
    "body { margin: 0; color: #334155; }"
    ".lead { margin: 0 0 4px 0; color: #101828; font-size: 1em; "
    " line-height: 1.25; }"
    ".body-line { margin: 0; color: #4b5563; font-size: 1em; "
    "line-height: 1.3; }"
    ".meta-label { margin: 5px 0 2px 0; color: #9ca3af; "
    "font-size: 0.77em;  }"
    ".meta-line { margin: 0; color: #6b7280; font-size: 0.92em; "
    "line-height: 1.3; }"
    ".term-row { margin: 2px 0; color: #4b5563; font-size: 0.92em; "
    "line-height: 1.3; }"
    ".term-name { color: #1f2937;  }"
    ".command { margin: 3px 0 2px 0; padding: 3px 7px; color: #26384c; "
    "background: #f3f4f6; font-family: 'Cascadia Mono', Consolas, monospace; "
    "font-size: 0.92em; white-space: pre-wrap; }"
    "code { color: #26384c; background: #f3f4f6; "
    "font-family: 'Cascadia Mono', Consolas, monospace; }"
)

_CODE_SYNTAX = re.compile(
    r"(?:=>|->|:=|==|!=|<=|>=|"
    r"\b(?:def|class|import|from|return|function|const|let|var|select|where|insert|delete|update|join)\b|"
    r"\{[^}]*\}|\[[^\]]*\])"
)


def looks_like_code(text: str) -> bool:
    """Heuristic backstop: long code/command blocks shouldn't show a translation."""
    if not text or not text.strip():
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    if len(lines) >= 3 and _CODE_SYNTAX.search(text):
        return True
    if any(len(line) > 160 for line in lines):
        return True
    if len(lines) == 1 and len(lines[0]) > 120:
        return True
    return False


def build_result_html(
    *,
    translation: str,
    explanation: str,
    source_text: str = "",
    terms: list[dict] | None = None,
) -> str:
    translation = compact_line_breaks(translation)
    explanation = compact_line_breaks(explanation)
    parts: list[str] = []
    if translation and not looks_like_code(source_text):
        parts.append('<div class="meta-label">翻译</div>')
        parts.append(render_lines(translation))
    if explanation:
        lead, body = split_lead(explanation)
        parts.append(compose_html(lead, body))
    elif not translation:
        parts.append(compose_html("没有可显示的结果。", ""))
    rendered_terms = render_terms(terms or [])
    if rendered_terms:
        parts.extend(
            [
                '<div class="meta-label">术语解释</div>',
                rendered_terms,
            ]
        )
    return "".join(parts)


def render_terms(terms: list[dict]) -> str:
    parts: list[str] = []
    for item in terms:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        chinese_name = str(item.get("chinese_name") or "").strip()
        explanation = compact_line_breaks(
            str(item.get("beginner_explanation") or "")
        )
        if not term:
            continue
        title = term
        if chinese_name and normalized_key(chinese_name) != normalized_key(term):
            title = f"{term} · {chinese_name}"
        detail = (
            f" — {format_inline_code(explanation)}" if explanation else ""
        )
        parts.append(
            '<div class="term-row">'
            f'<span class="term-name">{html.escape(title)}</span>{detail}'
            "</div>"
        )
    return "".join(parts)


def compose_html(lead: str, body: str) -> str:
    lead_html = format_inline_code(lead or "没有可显示的结果。")
    parts = [f'<div class="lead">{lead_html}</div>']
    if body:
        parts.append(render_lines(body))
    return "".join(parts)


def split_lead(text: str) -> tuple[str, str]:
    normalized = compact_line_breaks(text)
    if not normalized:
        return "", ""
    first_line, separator, remaining = normalized.partition("\n")
    if separator:
        return first_line.strip(), remaining.strip()
    match = re.match(r"^(.{1,120}?[。！？!?])\s*(.*)$", normalized, re.DOTALL)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return normalized, ""


def render_lines(text: str, *, meta: bool = False) -> str:
    class_name = "meta-line" if meta else "body-line"
    parts: list[str] = []
    for line in compact_line_breaks(text).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        command_match = re.match(
            r"^(.*?[：:]\s*)?((?:pip|python|py|npm|pnpm|yarn|git|docker|"
            r"conda|poetry|uv|cargo|go|mvn|gradle|dotnet|winget|brew|sudo|cd)"
            r"\s+.+)$",
            stripped,
            re.IGNORECASE,
        )
        if command_match:
            prefix = (command_match.group(1) or "").rstrip("：: ")
            if prefix:
                parts.append(
                    f'<div class="{class_name}">{format_inline_code(prefix)}</div>'
                )
            parts.append(
                f'<div class="command">{html.escape(command_match.group(2))}</div>'
            )
            continue
        if re.match(r"^(?:[A-Za-z]:\\|/)[^\n]+$", stripped):
            parts.append(f'<div class="command">{html.escape(stripped)}</div>')
            continue
        parts.append(
            f'<div class="{class_name}">{format_inline_code(stripped)}</div>'
        )
    return "".join(parts)


def format_inline_code(text: str) -> str:
    parts = re.split(r"(\x60[^\x60]+\x60)", text)
    output: list[str] = []
    marker = chr(96)
    for part in parts:
        if len(part) >= 2 and part.startswith(marker) and part.endswith(marker):
            output.append(f"<code>{html.escape(part[1:-1])}</code>")
        else:
            output.append(html.escape(part))
    return "".join(output)


def normalized_key(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()
