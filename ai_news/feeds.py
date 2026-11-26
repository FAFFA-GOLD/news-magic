"""Load and parse RSS/Atom feeds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import feedparser
import requests
import yaml

from ai_news.config import Settings


@dataclass
class FeedEntry:
    source: str
    url: str
    title: str
    rss_summary: str | None
    published_at: datetime | None


def load_feed_definitions(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    feeds = data.get("feeds") or []
    if not isinstance(feeds, list):
        raise ValueError("feeds.yaml: 'feeds' must be a list")
    return [
        {"source": str(item["source"]), "url": str(item["url"])}
        for item in feeds
        if item.get("source") and item.get("url")
    ]


def parse_published(entry: Any) -> Optional[datetime]:
    struct = getattr(entry, "published_parsed", None) or getattr(
        entry, "updated_parsed", None
    )
    if struct:
        return datetime(*struct[:6], tzinfo=timezone.utc)
    return None


def strip_html_snippet(html: str | None) -> str | None:
    if not html:
        return None
    import re

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def fetch_feed_entries(
    feed_meta: dict[str, str],
    settings: Settings,
    *,
    since: datetime,
) -> list[FeedEntry]:
    source = feed_meta["source"]
    url = feed_meta["url"]
    print(f"=== Fetching: {source} ({url}) ===")

    try:
        resp = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AI-News-Pipeline/2.0)"},
        )
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as exc:
        print(f"[WARN] feed failed: {source} ({exc!r})")
        return []

    entries: list[FeedEntry] = []
    for entry in getattr(parsed, "entries", [])[: settings.max_entries_per_feed]:
        link = getattr(entry, "link", None)
        title = getattr(entry, "title", None)
        if not link or not title:
            continue
        published = parse_published(entry)
        if published and published < since:
            continue
        summary = strip_html_snippet(getattr(entry, "summary", None)) or strip_html_snippet(
            getattr(entry, "description", None)
        )
        entries.append(
            FeedEntry(
                source=source,
                url=link.strip(),
                title=title.strip(),
                rss_summary=summary,
                published_at=published,
            )
        )

    print(f" -> {len(entries)} entries in window")
    return entries


def collect_recent_entries(settings: Settings) -> list[FeedEntry]:
    since = datetime.now(timezone.utc) - timedelta(hours=settings.hours_window)
    feed_defs = load_feed_definitions(settings.feeds_path)
    all_entries: list[FeedEntry] = []
    seen_urls: set[str] = set()
    for meta in feed_defs:
        for item in fetch_feed_entries(meta, settings, since=since):
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            all_entries.append(item)
    return all_entries