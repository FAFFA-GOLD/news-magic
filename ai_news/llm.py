"""Pluggable LLM summarization (Gemini default, OpenAI-compatible fallback)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import requests

from ai_news.config import CATEGORIES, Settings
from ai_news.gemini_models import (
    GeminiRuntime,
    LlmClientError,
    LlmProbeState,
    reselect_after_404,
)
from ai_news.http_retry import request_with_retry
from ai_news.json_parse import parse_llm_json

FALLBACK_TAG = "要約未処理"

_gemini_last_call: float = 0.0

ANALYSIS_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary_ja": {
            "type": "string",
            "description": "2〜4文の日本語要約",
        },
        "importance": {
            "type": "integer",
            "description": "1(低)〜5(高)",
        },
        "category": {
            "type": "string",
            "enum": list(CATEGORIES),
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["summary_ja", "importance", "category", "tags"],
}


@dataclass
class ArticleAnalysis:
    summary_ja: str
    importance: int
    category: str
    tags: list[str]
    used_fallback: bool = False


SYSTEM_HINT = """あなたはAI業界ニュースの編集者です。指定スキーマのJSONのみを返してください。
カテゴリは次のいずれか1つ: {categories}
重要度は1(低)〜5(高)の整数。タグは日本語または英語で最大5個。"""

USER_TEMPLATE = """タイトル: {title}
ソース: {source}
本文抜粋（{n}文字まで）:
{text}

記事を分析し、summary_ja・importance・category・tags を出力してください。"""

USER_TEMPLATE_SHORT = """タイトル: {title}
ソース: {source}
本文抜粋:
{text}

日本語要約は1〜2文（200字以内）に短く。importance・category・tags は同じスキーマで。"""


def tags_for_storage(analysis: ArticleAnalysis) -> list[str]:
    tags = [t for t in analysis.tags if t != FALLBACK_TAG]
    if analysis.used_fallback and FALLBACK_TAG not in tags:
        tags.append(FALLBACK_TAG)
    return tags[:10]


def _clamp_importance(value: int) -> int:
    return max(1, min(5, int(value)))


def _normalize_category(cat: str) -> str:
    if cat in CATEGORIES:
        return cat
    for c in CATEGORIES:
        if c in cat:
            return c
    return "業界動向"


def _cap_llm_input(
    settings: Settings,
    body_text: str,
    rss_summary: str | None,
    title: str,
) -> str:
    limit = settings.gemini_summary_input_max_chars
    text = body_text[:limit]
    if not text.strip():
        text = (rss_summary or title)[:limit]
    return text


def _fallback_analysis(title: str, rss_summary: str | None) -> ArticleAnalysis:
    if rss_summary:
        summary = rss_summary[:400]
        if len(rss_summary) > 400:
            summary += "…"
    else:
        summary = f"「{title}」に関する新着記事です。詳細は元記事を参照してください。"
    return ArticleAnalysis(
        summary_ja=summary,
        importance=3,
        category="業界動向",
        tags=[FALLBACK_TAG],
        used_fallback=True,
    )


def _analysis_from_dict(data: dict[str, Any]) -> ArticleAnalysis:
    summary = str(data.get("summary_ja") or "").strip()
    if not summary:
        raise ValueError("empty summary_ja from LLM")
    tags = [str(t) for t in (data.get("tags") or []) if str(t) != FALLBACK_TAG][:5]
    return ArticleAnalysis(
        summary_ja=summary,
        importance=_clamp_importance(int(data.get("importance", 3))),
        category=_normalize_category(str(data.get("category", "業界動向"))),
        tags=tags,
        used_fallback=False,
    )


def analyze_article(
    *,
    settings: Settings,
    title: str,
    source: str,
    body_text: str,
    rss_summary: str | None,
    gemini: GeminiRuntime | None = None,
    probe: LlmProbeState | None = None,
) -> ArticleAnalysis:
    if not settings.llm_enabled:
        return _fallback_analysis(title, rss_summary)

    text = _cap_llm_input(settings, body_text, rss_summary, title)
    system = SYSTEM_HINT.format(categories=", ".join(CATEGORIES))

    try:
        if settings.gemini_api_key:
            if gemini is None:
                raise ValueError("GeminiRuntime is required when GEMINI_API_KEY is set")
            data = _gemini_generate_json(
                settings,
                gemini,
                system,
                title,
                source,
                text,
            )
        else:
            prompt = USER_TEMPLATE.format(
                title=title, source=source, text=text, n=len(text)
            )
            data = _openai_compatible_generate(settings, system, prompt)
        analysis = _analysis_from_dict(data)
        if probe:
            probe.record_success()
        return analysis
    except LlmClientError:
        if probe:
            probe.record_client_error()
        raise
    except Exception as exc:
        print(f"[WARN] LLM summarization failed ({exc!r}); using RSS fallback")
        return _fallback_analysis(title, rss_summary)


def _pace_gemini(settings: Settings) -> None:
    global _gemini_last_call
    if settings.gemini_pace_seconds <= 0:
        return
    now = time.monotonic()
    elapsed = now - _gemini_last_call
    if _gemini_last_call > 0 and elapsed < settings.gemini_pace_seconds:
        time.sleep(settings.gemini_pace_seconds - elapsed)
    _gemini_last_call = time.monotonic()


def _gemini_generation_config(settings: Settings, model: str) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "temperature": 0.3,
        "maxOutputTokens": settings.gemini_max_output_tokens,
        "responseMimeType": "application/json",
        "responseSchema": ANALYSIS_RESPONSE_SCHEMA,
    }
    lower = model.lower()
    if "3." in lower or "thinking" in lower:
        cfg["thinkingConfig"] = {"thinkingBudget": 512}
    return cfg


def _gemini_generate_json(
    settings: Settings,
    gemini: GeminiRuntime,
    system: str,
    title: str,
    source: str,
    text: str,
) -> dict[str, Any]:
    attempts = [
        (USER_TEMPLATE, text),
        (USER_TEMPLATE_SHORT, text[: min(len(text), 1500)]),
    ]
    last_err: Exception | None = None
    for template, chunk in attempts:
        prompt = template.format(title=title, source=source, text=chunk, n=len(chunk))
        try:
            raw = _gemini_raw_text(settings, gemini, system, prompt)
            data = parse_llm_json(raw)
            if data:
                return data
            raise ValueError("JSON parse/repair returned no data")
        except LlmClientError:
            raise
        except Exception as exc:
            last_err = exc
            print(f"[WARN] Gemini JSON attempt failed ({exc!r}); retrying…")
    raise ValueError(f"Gemini JSON failed after retries: {last_err!r}")


def _gemini_raw_text(
    settings: Settings,
    gemini: GeminiRuntime,
    system: str,
    user: str,
) -> str:
    last_error: LlmClientError | None = None
    for _ in range(2):
        _pace_gemini(settings)
        model = gemini.resolved_model
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={gemini.api_key}"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{system}\n\n{user}"}],
                }
            ],
            "generationConfig": _gemini_generation_config(settings, model),
        }
        session = requests.Session()
        resp = request_with_retry(session, "POST", url, json=payload, timeout=120)
        if resp.status_code == 404:
            if reselect_after_404(gemini):
                last_error = LlmClientError(404, resp.text)
                continue
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            raise LlmClientError(resp.status_code, resp.text[:2000])
        resp.raise_for_status()
        body = resp.json()
        return (
            body.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
    if last_error:
        raise last_error
    raise LlmClientError(404, "Gemini model not found after re-select")


def _openai_compatible_generate(settings: Settings, system: str, user: str) -> dict:
    url = f"{settings.openai_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.openai_model,
        "temperature": 0.3,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    session = requests.Session()
    resp = request_with_retry(session, "POST", url, headers=headers, json=payload, timeout=90)
    if 400 <= resp.status_code < 500 and resp.status_code != 429:
        raise LlmClientError(resp.status_code, resp.text[:2000])
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    data = parse_llm_json(text)
    if not data:
        raise ValueError("OpenAI JSON parse failed")
    return data