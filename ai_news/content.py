"""Fetch and normalize article body text."""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup

from ai_news.config import CONTENT_MAX_CHARS


def fetch_article_content(url: str) -> str | None:
    try:
        resp = requests.get(
            url,
            timeout=12,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; AI-News-Pipeline/2.0)",
            },
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"[WARN] fetch_article_content failed: {url} ({exc!r})")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    candidates = []
    if soup.find("article"):
        candidates.append(soup.find("article"))
    if soup.find("main"):
        candidates.append(soup.find("main"))
    candidates += soup.select("[class*='article'], [class*='content']")

    for node in candidates:
        if not node:
            continue
        text = node.get_text(separator="\n", strip=True)
        if text and len(text) > 200:
            return text[:CONTENT_MAX_CHARS]

    body = soup.body or soup
    text = body.get_text(separator="\n", strip=True)
    if not text:
        return None
    return text[:CONTENT_MAX_CHARS]