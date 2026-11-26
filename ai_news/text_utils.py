"""Normalize text extracted from RSS/HTML."""

from __future__ import annotations

import html
import re


def clean_rss_text(text: str | None) -> str | None:
    if not text:
        return None
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None