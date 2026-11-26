"""Notion database integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from ai_news.config import CATEGORIES, Settings
from ai_news.llm import ArticleAnalysis

NOTION_VERSION = "2022-06-28"


@dataclass
class SavedArticle:
    source: str
    url: str
    title: str
    summary_ja: str
    importance: int
    category: str
    tags: list[str]
    published_at: datetime | None
    fetched_at: datetime


class NotionClient:
    def __init__(self, token: str, database_id: str) -> None:
        self.database_id = database_id.replace("-", "")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )

    def url_exists(self, url: str) -> bool:
        payload = {
            "filter": {"property": "URL", "url": {"equals": url}},
            "page_size": 1,
        }
        resp = self.session.post(
            f"https://api.notion.com/v1/databases/{self.database_id}/query",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return bool(resp.json().get("results"))

    def create_article(self, article: SavedArticle) -> str | None:
        props = _article_properties(article)
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": props,
        }
        resp = self.session.post(
            "https://api.notion.com/v1/pages", json=payload, timeout=30
        )
        resp.raise_for_status()
        return resp.json().get("id")

    def create_digest_page(
        self,
        *,
        parent_page_id: str,
        title: str,
        markdown_body: str,
    ) -> str | None:
        parent = parent_page_id.replace("-", "")
        children = _markdown_to_blocks(markdown_body)
        payload: dict[str, Any] = {
            "parent": {"page_id": parent},
            "properties": {
                "title": {"title": [{"text": {"content": title[:2000]}}]},
            },
            "children": children[:100],
        }
        resp = self.session.post(
            "https://api.notion.com/v1/pages", json=payload, timeout=60
        )
        resp.raise_for_status()
        return resp.json().get("id")


def save_to_notion(
    client: NotionClient,
    *,
    source: str,
    url: str,
    title: str,
    analysis: ArticleAnalysis,
    published_at: datetime | None,
) -> SavedArticle | None:
    if client.url_exists(url):
        print(f"[SKIP] duplicate URL in Notion: {title[:60]}")
        return None

    fetched_at = datetime.now(timezone.utc)
    article = SavedArticle(
        source=source,
        url=url,
        title=title,
        summary_ja=analysis.summary_ja,
        importance=analysis.importance,
        category=analysis.category,
        tags=analysis.tags,
        published_at=published_at,
        fetched_at=fetched_at,
    )
    page_id = client.create_article(article)
    print(f"Notion saved: {title[:60]} (page={page_id})")
    return article


def _article_properties(article: SavedArticle) -> dict[str, Any]:
    props: dict[str, Any] = {
        "タイトル": {"title": [{"text": {"content": article.title[:2000]}}]},
        "要約": {
            "rich_text": [{"text": {"content": article.summary_ja[:2000]}}],
        },
        "重要度": {"number": article.importance},
        "カテゴリ": {"select": {"name": article.category}},
        "ソース": {"select": {"name": article.source[:100]}},
        "URL": {"url": article.url[:2000]},
        "取得日": {"date": {"start": _date_iso(article.fetched_at)}},
    }
    if article.tags:
        props["タグ"] = {
            "multi_select": [{"name": t[:100]} for t in article.tags[:10]],
        }
    if article.published_at:
        props["公開日"] = {"date": {"start": _date_iso(article.published_at)}}
    return props


def _date_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _markdown_to_blocks(markdown_body: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    chunk = ""
    for line in markdown_body.splitlines():
        chunk += line + "\n"
        if len(chunk) > 1800:
            blocks.append(_paragraph_block(chunk))
            chunk = ""
    if chunk.strip():
        blocks.append(_paragraph_block(chunk))
    return blocks


def _paragraph_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text[:2000]}}],
        },
    }


DATABASE_SCHEMA: dict[str, Any] = {
    "タイトル": {"title": {}},
    "要約": {"rich_text": {}},
    "重要度": {"number": {"format": "number"}},
    "カテゴリ": {"select": {"options": [{"name": c, "color": "default"} for c in CATEGORIES]}},
    "タグ": {"multi_select": {"options": []}},
    "ソース": {"select": {"options": []}},
    "URL": {"url": {}},
    "公開日": {"date": {}},
    "取得日": {"date": {}},
}


def create_database(
    token: str,
    parent_page_id: str,
    title: str = "AIニュース記事",
) -> dict[str, Any]:
    parent = parent_page_id.replace("-", "")
    payload = {
        "parent": {"type": "page_id", "page_id": parent},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": DATABASE_SCHEMA,
    }
    resp = requests.post(
        "https://api.notion.com/v1/databases",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def notion_client_from_settings(settings: Settings) -> NotionClient | None:
    if not settings.notion_enabled:
        return None
    assert settings.notion_token and settings.notion_database_id
    return NotionClient(settings.notion_token, settings.notion_database_id)