"""Build Notion block trees for the morning digest (not raw markdown)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ai_news.config import CATEGORIES
from ai_news.llm import FALLBACK_TAG
from ai_news.notion_store import SavedArticle

JST = ZoneInfo("Asia/Tokyo")
DIGEST_CAP_PER_CATEGORY = 10
FALLBACK_SECTION_CAP = 5


def _one_line_summary(art: SavedArticle, limit: int = 120) -> str:
    line = (art.summary_ja or "").split("\n")[0].strip()
    if len(line) > limit:
        return line[: limit - 1] + "…"
    return line


def _rich_text(
    content: str,
    *,
    bold: bool = False,
    link: str | None = None,
) -> dict[str, Any]:
    content = content[:2000]
    text: dict[str, Any] = {"content": content}
    if link:
        text["link"] = {"url": link[:2000]}
    item: dict[str, Any] = {"type": "text", "text": text}
    if bold:
        item["annotations"] = {"bold": True}
    return item


def heading_2(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [_rich_text(text[:2000])]},
    }


def paragraph(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [_rich_text(text[:2000])]},
    }


def article_bullet(art: SavedArticle, *, with_summary: bool = True) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [
        _rich_text(f"[{art.importance}] ", bold=True),
        _rich_text(art.title[:500], link=art.url),
    ]
    if with_summary:
        parts.append(_rich_text(f" — {_one_line_summary(art)}"))
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": parts},
    }


def fallback_bullet(art: SavedArticle) -> dict[str, Any]:
    return article_bullet(art, with_summary=False)


def is_digest_fallback(art: SavedArticle) -> bool:
    return FALLBACK_TAG in art.tags


def build_notion_digest_blocks(
    articles: list[SavedArticle],
    *,
    when: datetime | None = None,
) -> list[dict[str, Any]]:
    when = when or datetime.now(timezone.utc)
    jst_label = when.astimezone(JST).strftime("%Y-%m-%d")

    main_articles = [a for a in articles if not is_digest_fallback(a)]
    fallback_articles = [a for a in articles if is_digest_fallback(a)]

    blocks: list[dict[str, Any]] = []
    if not articles:
        blocks.append(paragraph(f"AIダイジェスト {jst_label} (JST) — 直近の新着記事はありませんでした。"))
        return blocks

    blocks.append(
        paragraph(
            f"AIダイジェスト {jst_label} (JST) — 全 {len(main_articles)} 件"
            + (
                f"（要約未処理 {len(fallback_articles)} 件は末尾）"
                if fallback_articles
                else ""
            )
        )
    )

    grouped: dict[str, list[SavedArticle]] = defaultdict(list)
    for art in main_articles:
        cat = art.category if art.category in CATEGORIES else "業界動向"
        grouped[cat].append(art)

    for cat in CATEGORIES:
        items = grouped.get(cat)
        if not items:
            continue
        sorted_items = sorted(items, key=lambda a: (-a.importance, a.title))
        blocks.append(heading_2(cat))
        shown = sorted_items[:DIGEST_CAP_PER_CATEGORY]
        for art in shown:
            blocks.append(article_bullet(art))
        extra = len(sorted_items) - len(shown)
        if extra > 0:
            blocks.append(
                paragraph(f"ほか {extra} 件は AI記事 データベースを参照")
            )

    if fallback_articles:
        blocks.append(heading_2("要約未処理"))
        fb_sorted = sorted(fallback_articles, key=lambda a: (-a.importance, a.title))
        shown_fb = fb_sorted[:FALLBACK_SECTION_CAP]
        for art in shown_fb:
            blocks.append(fallback_bullet(art))
        extra_fb = len(fb_sorted) - len(shown_fb)
        if extra_fb > 0:
            blocks.append(
                paragraph(f"ほか {extra_fb} 件の要約未処理は AI記事 データベースを参照")
            )

    return blocks