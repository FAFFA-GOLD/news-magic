"""Notion database integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from ai_news.config import CATEGORIES, Settings
from ai_news.http_retry import request_with_retry
from ai_news.llm import FALLBACK_TAG, ArticleAnalysis, tags_for_storage

NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"


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


@dataclass
class NotionArticleRow:
    page_id: str
    source: str
    url: str
    title: str
    summary_ja: str
    importance: int
    category: str
    tags: list[str]
    published_at: datetime | None
    fetched_at: datetime | None


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

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{NOTION_API}/{path.lstrip('/')}"
        resp = request_with_retry(self.session, method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def preload_recent_urls(self, days: int) -> set[str]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        urls: set[str] = set()
        cursor: str | None = None
        while True:
            payload: dict[str, Any] = {
                "filter": {
                    "property": "取得日",
                    "date": {"on_or_after": since},
                },
                "page_size": 100,
            }
            if cursor:
                payload["start_cursor"] = cursor
            data = self._request(
                "POST", f"databases/{self.database_id}/query", json=payload
            )
            for page in data.get("results", []):
                url = _prop_url(page.get("properties", {}))
                if url:
                    urls.add(url)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        print(f"Notion dedupe cache: {len(urls)} URLs (last {days} days)")
        return urls

    def create_article(
        self,
        article: SavedArticle,
        *,
        analysis: ArticleAnalysis | None = None,
    ) -> str | None:
        props = _article_properties(article, analysis=analysis)
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": props,
        }
        data = self._request("POST", "pages", json=payload)
        return data.get("id")

    def update_article_page(self, page_id: str, analysis: ArticleAnalysis) -> None:
        tags = tags_for_storage(analysis)
        props: dict[str, Any] = {
            "要約": {
                "rich_text": [{"text": {"content": analysis.summary_ja[:2000]}}],
            },
            "重要度": {"number": analysis.importance},
            "カテゴリ": {"select": {"name": analysis.category}},
            "タグ": {"multi_select": [{"name": t[:100]} for t in tags]},
        }
        self._request("PATCH", f"pages/{page_id.replace('-', '')}", json={"properties": props})

    def query_fallback_articles(self, *, days: int = 14) -> list[NotionArticleRow]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        filter_body = {
            "and": [
                {
                    "property": "取得日",
                    "date": {"on_or_after": since},
                },
                {
                    "or": [
                        {
                            "property": "タグ",
                            "multi_select": {"contains": FALLBACK_TAG},
                        },
                        {
                            "and": [
                                {"property": "重要度", "number": {"equals": 3}},
                                {
                                    "property": "カテゴリ",
                                    "select": {"equals": "業界動向"},
                                },
                            ],
                        },
                    ],
                },
            ]
        }
        return self._query_all_articles(filter_body)

    def query_articles_since_hours(self, hours: int) -> list[SavedArticle]:
        since_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
        since = since_dt.strftime("%Y-%m-%d")
        rows = self._query_all_articles(
            {
                "property": "取得日",
                "date": {"on_or_after": since},
            }
        )
        articles: list[SavedArticle] = []
        for row in rows:
            if row.fetched_at and row.fetched_at < since_dt:
                continue
            articles.append(
                SavedArticle(
                    source=row.source,
                    url=row.url,
                    title=row.title,
                    summary_ja=row.summary_ja,
                    importance=row.importance,
                    category=row.category,
                    tags=row.tags,
                    published_at=row.published_at,
                    fetched_at=row.fetched_at or datetime.now(timezone.utc),
                )
            )
        return articles

    def _query_all_articles(self, filter_body: dict[str, Any]) -> list[NotionArticleRow]:
        rows: list[NotionArticleRow] = []
        cursor: str | None = None
        while True:
            payload: dict[str, Any] = {
                "filter": filter_body,
                "page_size": 100,
            }
            if cursor:
                payload["start_cursor"] = cursor
            data = self._request(
                "POST", f"databases/{self.database_id}/query", json=payload
            )
            for page in data.get("results", []):
                row = _page_to_row(page)
                if row:
                    rows.append(row)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return rows

    def find_child_page_by_title(self, parent_page_id: str, title: str) -> str | None:
        parent = parent_page_id.replace("-", "")
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._request("GET", f"blocks/{parent}/children", params=params)
            for block in data.get("results", []):
                if block.get("type") != "child_page":
                    continue
                block_title = _plain_text(block.get("child_page", {}).get("title", []))
                if block_title == title:
                    return block.get("id")
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return None

    def upsert_digest_page(
        self,
        *,
        parent_page_id: str,
        title: str,
        markdown_body: str,
    ) -> str | None:
        page_id = self.find_child_page_by_title(parent_page_id, title)
        children = _markdown_to_blocks(markdown_body)[:100]
        if page_id:
            self._clear_block_children(page_id)
            if children:
                self._append_block_children(page_id, children)
            print(f"Notion digest page updated: {title}")
            return page_id

        parent = parent_page_id.replace("-", "")
        payload: dict[str, Any] = {
            "parent": {"page_id": parent},
            "properties": {
                "title": {"title": [{"text": {"content": title[:2000]}}]},
            },
            "children": children,
        }
        data = self._request("POST", "pages", json=payload)
        print(f"Notion digest page created: {title}")
        return data.get("id")

    def _clear_block_children(self, block_id: str) -> None:
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._request("GET", f"blocks/{block_id}/children", params=params)
            for block in data.get("results", []):
                bid = block.get("id")
                if bid:
                    self._request("PATCH", f"blocks/{bid}", json={"archived": True})
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    def _append_block_children(
        self, block_id: str, children: list[dict[str, Any]]
    ) -> None:
        for i in range(0, len(children), 100):
            chunk = children[i : i + 100]
            self._request(
                "PATCH",
                f"blocks/{block_id}/children",
                json={"children": chunk},
            )


def save_to_notion(
    client: NotionClient,
    *,
    source: str,
    url: str,
    title: str,
    analysis: ArticleAnalysis,
    published_at: datetime | None,
    existing_urls: set[str],
) -> SavedArticle | None:
    if url in existing_urls:
        print(f"[SKIP] duplicate URL in Notion: {title[:60]}")
        return None

    fetched_at = datetime.now(timezone.utc)
    tags = tags_for_storage(analysis)
    article = SavedArticle(
        source=source,
        url=url,
        title=title,
        summary_ja=analysis.summary_ja,
        importance=analysis.importance,
        category=analysis.category,
        tags=tags,
        published_at=published_at,
        fetched_at=fetched_at,
    )
    page_id = client.create_article(article, analysis=analysis)
    existing_urls.add(url)
    print(f"Notion saved: {title[:60]} (page={page_id})")
    return article


def publish_digest(
    settings: Settings,
    client: NotionClient,
    articles: list[SavedArticle],
    *,
    from_notion_hours: int | None = None,
) -> None:
    from ai_news.digest import build_digest_markdown, digest_title

    if from_notion_hours is not None:
        articles = client.query_articles_since_hours(from_notion_hours)
    digest_md = build_digest_markdown(articles)
    print("\n" + "=" * 60)
    print(digest_md)
    print("=" * 60)

    if settings.dry_run:
        return

    if settings.notion_parent_page_id:
        title = digest_title()
        client.upsert_digest_page(
            parent_page_id=settings.notion_parent_page_id,
            title=title,
            markdown_body=digest_md,
        )

    from ai_news.digest import post_digest_webhook

    post_digest_webhook(settings, digest_md)


def _article_properties(
    article: SavedArticle,
    *,
    analysis: ArticleAnalysis | None = None,
) -> dict[str, Any]:
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
    tags = article.tags
    if analysis is not None:
        tags = tags_for_storage(analysis)
    if tags:
        props["タグ"] = {
            "multi_select": [{"name": t[:100]} for t in tags[:10]],
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


def _plain_text(rich: list[dict[str, Any]]) -> str:
    parts = []
    for item in rich:
        if isinstance(item, dict):
            parts.append(item.get("plain_text") or item.get("text", {}).get("content", ""))
    return "".join(parts)


def _prop_url(properties: dict[str, Any]) -> str | None:
    prop = properties.get("URL") or {}
    return prop.get("url")


def _page_to_row(page: dict[str, Any]) -> NotionArticleRow | None:
    props = page.get("properties", {})
    url = _prop_url(props)
    title = _plain_text(props.get("タイトル", {}).get("title", []))
    if not url or not title:
        return None
    summary = _plain_text(props.get("要約", {}).get("rich_text", []))
    importance = props.get("重要度", {}).get("number") or 3
    category = (props.get("カテゴリ", {}).get("select") or {}).get("name") or "業界動向"
    source = (props.get("ソース", {}).get("select") or {}).get("name") or ""
    tags = [
        (t.get("name") or "")
        for t in props.get("タグ", {}).get("multi_select", [])
        if t.get("name")
    ]
    pub = (props.get("公開日", {}).get("date") or {}).get("start")
    fetched = (props.get("取得日", {}).get("date") or {}).get("start")
    return NotionArticleRow(
        page_id=page.get("id", ""),
        source=source,
        url=url,
        title=title,
        summary_ja=summary,
        importance=int(importance),
        category=category,
        tags=tags,
        published_at=_parse_date(pub),
        fetched_at=_parse_date(fetched),
    )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


DATABASE_SCHEMA: dict[str, Any] = {
    "タイトル": {"title": {}},
    "要約": {"rich_text": {}},
    "重要度": {"number": {"format": "number"}},
    "カテゴリ": {"select": {"options": [{"name": c, "color": "default"} for c in CATEGORIES]}},
    "タグ": {"multi_select": {"options": [{"name": FALLBACK_TAG, "color": "yellow"}]}},
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
    resp = request_with_retry(
        requests.Session(),
        "POST",
        f"{NOTION_API}/databases",
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