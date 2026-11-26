"""Normalize text extracted from RSS/HTML."""

from __future__ import annotations

import html
import re
from typing import Any


def clean_rss_text(text: str | None) -> str | None:
    if not text:
        return None
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def strip_leading_dash_artifact(text: str) -> str:
    return re.sub(r"^[\s]*-\s+", "", text).strip()


def normalize_stored_text(text: str, *, source: str = "") -> str:
    cleaned = clean_rss_text(text) or text.strip()
    cleaned = strip_leading_dash_artifact(cleaned)
    return cleaned


def normalize_stored_summary(text: str) -> str:
    return normalize_stored_text(text)


def normalize_feed_title(title: str, source: str, entry: Any | None = None) -> str:
    cleaned = clean_rss_text(title) or title.strip()
    cleaned = strip_leading_dash_artifact(cleaned)
    if entry is not None and "Google News" in source:
        cleaned = _prefer_google_news_headline(entry, source, cleaned)
    return cleaned or title.strip()


def _prefer_google_news_headline(entry: Any, source: str, current: str) -> str:
    """Use a longer headline when the feed title is only a publisher/source stub."""
    if len(current) > 40 and not _looks_like_source_stub(current, source):
        return current

    raw_title = clean_rss_text(getattr(entry, "title", None) or "") or ""
    if " - " in raw_title:
        head = strip_leading_dash_artifact(raw_title.split(" - ", 1)[0].strip())
        if len(head) > len(current) and not _looks_like_source_stub(head, source):
            return head

    summary = getattr(entry, "summary", None) or getattr(entry, "description", None) or ""
    plain = re.sub(r"<[^>]+>", " ", str(summary))
    plain = clean_rss_text(plain) or ""
    first = plain.split(".")[0].strip() if plain else ""
    if len(first) > len(current) + 10 and not _looks_like_source_stub(first, source):
        return first[:500]

    return current


def _looks_like_source_stub(title: str, source: str) -> bool:
    base = re.sub(r"\s*\(Google News[^)]*\)", "", source, flags=re.I).strip()
    base = base.split("(")[0].strip()
    if not base:
        return False
    t = title.strip().lower()
    b = base.lower()
    return t == b or t == f"- {b}" or len(t) < 20 and b.startswith(t)