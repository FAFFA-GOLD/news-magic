"""Morning digest formatting and delivery."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from ai_news.config import CATEGORIES, Settings
from ai_news.notion_store import SavedArticle

JST = ZoneInfo("Asia/Tokyo")


def build_digest_markdown(articles: list[SavedArticle], *, when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    jst_label = when.astimezone(JST).strftime("%Y-%m-%d")
    grouped: dict[str, list[SavedArticle]] = defaultdict(list)
    for art in articles:
        cat = art.category if art.category in CATEGORIES else "業界動向"
        grouped[cat].append(art)

    lines = [f"# AIダイジェスト {jst_label} (JST)", ""]
    if not articles:
        lines.append("_直近24時間の新着記事はありませんでした。_")
        return "\n".join(lines)

    for cat in CATEGORIES:
        items = grouped.get(cat)
        if not items:
            continue
        lines.append(f"## {cat}")
        lines.append("")
        for art in sorted(items, key=lambda a: (-a.importance, a.title)):
            one_line = art.summary_ja.split("\n")[0].strip()
            if len(one_line) > 120:
                one_line = one_line[:117] + "…"
            lines.append(
                f"- **[{art.importance}]** {art.title} — {one_line} "
                f"([リンク]({art.url}))"
            )
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def digest_title(when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    return f"AIダイジェスト {when.astimezone(JST).strftime('%Y-%m-%d')}"


def post_digest_webhook(settings: Settings, markdown: str) -> None:
    if not settings.digest_webhook_url:
        return
    payload = {"text": markdown[:39000]}
    try:
        resp = requests.post(settings.digest_webhook_url, json=payload, timeout=30)
        resp.raise_for_status()
        print("Digest webhook delivered.")
    except Exception as exc:
        print(f"[WARN] digest webhook failed: {exc!r}")


def filter_last_hours(
    articles: list[SavedArticle], hours: int
) -> list[SavedArticle]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return [a for a in articles if a.fetched_at >= since]