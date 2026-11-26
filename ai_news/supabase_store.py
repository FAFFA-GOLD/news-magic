"""Optional Supabase mirror of articles."""

from __future__ import annotations

from datetime import datetime

from ai_news.config import Settings
from ai_news.llm import ArticleAnalysis


def get_supabase_client(settings: Settings):
    if not settings.supabase_enabled:
        return None
    from supabase import create_client

    assert settings.supabase_url and settings.supabase_service_role_key
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def save_to_supabase(
    client,
    *,
    source: str,
    url: str,
    title: str,
    analysis: ArticleAnalysis,
    content_text: str | None,
    rss_summary: str | None,
    published_at: datetime | None,
) -> bool:
    existing = (
        client.table("articles")
        .select("id")
        .eq("url", url)
        .limit(1)
        .execute()
    )
    if existing.data:
        return False

    published_iso = published_at.isoformat() if published_at else None
    row = {
        "source": source,
        "url": url,
        "title": title,
        "summary": analysis.summary_ja,
        "content_raw": rss_summary,
        "content_text": content_text or rss_summary,
        "published_at": published_iso,
        "importance": analysis.importance,
        "category": analysis.category,
        "tags": analysis.tags,
    }
    # Extra columns may not exist on legacy schema — insert core fields only on failure
    try:
        client.table("articles").insert(row).execute()
    except Exception:
        core = {k: row[k] for k in row if k in {
            "source", "url", "title", "summary", "content_raw",
            "content_text", "published_at",
        }}
        client.table("articles").insert(core).execute()
    print(f"Supabase inserted: {title[:60]}")
    return True