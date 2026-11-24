"""Pluggable LLM summarization (Gemini default, OpenAI-compatible fallback)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import requests

from ai_news.config import CATEGORIES, Settings, SUMMARY_INPUT_MAX_CHARS


@dataclass
class ArticleAnalysis:
    summary_ja: str
    importance: int
    category: str
    tags: list[str]


SYSTEM_HINT = """あなたはAI業界ニュースの編集者です。記事を日本語で要約し、JSONのみを返してください。
カテゴリは次のいずれか1つ: {categories}
重要度は1(低)〜5(高)の整数。タグは日本語または英語で最大5個。"""

USER_TEMPLATE = """タイトル: {title}
ソース: {source}
本文抜粋:
{text}

次のJSON形式のみで回答:
{{"summary_ja": "2〜4文の日本語要約", "importance": 3, "category": "業界動向", "tags": ["タグ1"]}}"""


def _clamp_importance(value: int) -> int:
    return max(1, min(5, int(value)))


def _normalize_category(cat: str) -> str:
    if cat in CATEGORIES:
        return cat
    for c in CATEGORIES:
        if c in cat:
            return c
    return "業界動向"


def _parse_json_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


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
        tags=[],
    )


def analyze_article(
    *,
    settings: Settings,
    title: str,
    source: str,
    body_text: str,
    rss_summary: str | None,
) -> ArticleAnalysis:
    if not settings.llm_enabled:
        return _fallback_analysis(title, rss_summary)

    text = body_text[:SUMMARY_INPUT_MAX_CHARS]
    if not text.strip():
        text = (rss_summary or title)[:SUMMARY_INPUT_MAX_CHARS]

    prompt = USER_TEMPLATE.format(title=title, source=source, text=text)
    system = SYSTEM_HINT.format(categories=", ".join(CATEGORIES))

    try:
        if settings.gemini_api_key:
            data = _gemini_generate(settings, system, prompt)
        else:
            data = _openai_compatible_generate(settings, system, prompt)
        return ArticleAnalysis(
            summary_ja=str(data.get("summary_ja") or "").strip()
            or _fallback_analysis(title, rss_summary).summary_ja,
            importance=_clamp_importance(int(data.get("importance", 3))),
            category=_normalize_category(str(data.get("category", "業界動向"))),
            tags=[str(t) for t in (data.get("tags") or [])][:5],
        )
    except Exception as exc:
        print(f"[WARN] LLM summarization failed ({exc!r}); using RSS fallback")
        return _fallback_analysis(title, rss_summary)


def _gemini_generate(settings: Settings, system: str, user: str) -> dict:
    model = settings.gemini_model
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={settings.gemini_api_key}"
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{system}\n\n{user}"}],
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 512,
            "responseMimeType": "application/json",
        },
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    body = resp.json()
    text = (
        body.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )
    return _parse_json_response(text)


def _openai_compatible_generate(settings: Settings, system: str, user: str) -> dict:
    url = f"{settings.openai_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.openai_model,
        "temperature": 0.3,
        "max_tokens": 512,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return _parse_json_response(text)