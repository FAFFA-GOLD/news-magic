"""Notion database integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from ai_news.config import CATEGORIES, Settings
from ai_news.http_retry import request_with_retry
from ai_news.llm import FALLBACK_TAG, ArticleAnalysis, tags_for_storage
from ai_news.text_utils import normalize_stored_summary, normalize_stored_text

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
        if not resp.ok:
            body = resp.text[:8000] if resp.text else "(empty body)"
            print(
                f"[ERROR] Notion HTTP {resp.status_code} {method} {path}: {body}"
            )
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
                "rich_text": [
                    {"text": {"content": normalize_stored_summary(analysis.summary_ja)[:2000]}}
                ],
            },
            "重要度": {"number": analysis.importance},
            "カテゴリ": {"select": {"name": analysis.category}},
            "タグ": {"multi_select": [{"name": t[:100]} for t in tags]},
        }
        self._request("PATCH", f"pages/{page_id.replace('-', '')}", json={"properties": props})

    def patch_article_text(
        self,
        page_id: str,
        *,
        title: str,
        summary_ja: str,
    ) -> None:
        props: dict[str, Any] = {
            "タイトル": {"title": [{"text": {"content": title[:2000]}}]},
            "要約": {
                "rich_text": [{"text": {"content": summary_ja[:2000]}}],
            },
        }
        self._request(
            "PATCH",
            f"pages/{page_id.replace('-', '')}",
            json={"properties": props},
        )

    def query_fallback_articles(self, *, days: int = 14) -> list[NotionArticleRow]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        # Notion allows at most 2 filter nesting levels; fallback rules are applied in Python.
        filter_body: dict[str, Any] = {
            "property": "取得日",
            "date": {"on_or_after": since},
        }
        all_rows = self._query_all_articles(filter_body)
        candidates = [
            row
            for row in all_rows
            if is_fallback_candidate(
                tags=row.tags,
                importance=row.importance,
                category=row.category,
            )
        ]
        print(
            f"Notion fallback candidates: {len(candidates)} / {len(all_rows)} "
            f"(取得日 >= {since})"
        )
        return candidates

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
        return self.resolve_digest_page_id(parent_page_id, title)

    def resolve_digest_page_id(self, parent_page_id: str, title: str) -> str | None:
        parent = parent_page_id.replace("-", "")
        matching: list[str] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._request("GET", f"blocks/{parent}/children", params=params)
            for block in data.get("results", []):
                if block.get("type") != "child_page":
                    continue
                block_title = parse_child_page_title(
                    block.get("child_page", {}).get("title")
                )
                if block_title == title:
                    bid = block.get("id")
                    if bid:
                        matching.append(bid)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        if not matching:
            return None
        if len(matching) == 1:
            return matching[0]

        best_id = matching[0]
        best_ts = ""
        for pid in matching:
            page = self._request("GET", f"pages/{pid}")
            ts = page.get("last_edited_time", "")
            if ts > best_ts:
                best_ts = ts
                best_id = pid
        others = [pid for pid in matching if pid != best_id]
        print(
            f"[WARN] Duplicate digest pages titled {title!r}: "
            f"updating {best_id}; also found {others}"
        )
        return best_id

    def upsert_digest_page(
        self,
        *,
        parent_page_id: str,
        title: str,
        blocks: list[dict[str, Any]],
    ) -> str | None:
        page_id = self.resolve_digest_page_id(parent_page_id, title)
        if page_id:
            self._clear_block_children(page_id)
            if blocks:
                self._append_block_children(page_id, blocks)
            print(f"Notion digest page updated: {title}")
            return page_id

        parent = parent_page_id.replace("-", "")
        initial = blocks[:100]
        payload: dict[str, Any] = {
            "parent": {"page_id": parent},
            "properties": {
                "title": {"title": [{"text": {"content": title[:2000]}}]},
            },
            "children": initial,
        }
        data = self._request("POST", "pages", json=payload)
        page_id = data.get("id")
        if page_id and len(blocks) > 100:
            self._append_block_children(page_id, blocks[100:])
        print(f"Notion digest page created: {title}")
        return page_id

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
    title = normalize_stored_text(title, source=source)
    summary_ja = normalize_stored_summary(analysis.summary_ja)
    article = SavedArticle(
        source=source,
        url=url,
        title=title,
        summary_ja=summary_ja,
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
    from ai_news.digest_blocks import build_notion_digest_blocks

    if from_notion_hours is not None:
        articles = client.query_articles_since_hours(from_notion_hours)
    digest_md = build_digest_markdown(articles)
    blocks = build_notion_digest_blocks(articles)
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
            blocks=blocks,
        )

    from ai_news.digest import post_digest_webhook

    post_digest_webhook(settings, digest_md)


def cleanup_article_text_in_notion(
    client: NotionClient,
    *,
    days: int,
) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = client._query_all_articles(
        {"property": "取得日", "date": {"on_or_after": since}}
    )
    updated = 0
    for row in rows:
        new_title = normalize_stored_text(row.title, source=row.source)
        new_summary = normalize_stored_summary(row.summary_ja)
        if new_title == row.title and new_summary == row.summary_ja:
            continue
        client.patch_article_text(
            row.page_id,
            title=new_title,
            summary_ja=new_summary,
        )
        updated += 1
        print(f"Text cleanup: {row.title[:40]!r} -> {new_title[:40]!r}")
    print(f"[SUMMARY] Text cleanup: {updated} rows updated")
    return updated


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


def parse_child_page_title(title_field: Any) -> str:
    """Notion child_page.title may be a plain string or rich_text array."""
    if title_field is None:
        return ""
    if isinstance(title_field, str):
        return title_field
    if isinstance(title_field, list):
        return _plain_text(title_field)
    return str(title_field)


def _plain_text(rich: list[dict[str, Any]]) -> str:
    parts = []
    for item in rich:
        if isinstance(item, dict):
            parts.append(item.get("plain_text") or item.get("text", {}).get("content", ""))
    return "".join(parts)


def is_fallback_candidate(
    *,
    tags: list[str],
    importance: int,
    category: str,
) -> bool:
    """True if row should be re-analyzed (タグ 要約未処理 のみ)."""
    return FALLBACK_TAG in tags


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