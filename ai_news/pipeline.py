"""Main collection pipeline."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from ai_news.config import Settings
from ai_news.content import fetch_article_content
from ai_news.digest import (
    build_digest_markdown,
    digest_title,
    post_digest_webhook,
)
from ai_news.feeds import collect_recent_entries
from ai_news.llm import analyze_article
from ai_news.notion_store import SavedArticle, notion_client_from_settings, save_to_notion
from ai_news.supabase_store import get_supabase_client, save_to_supabase


def run(settings: Settings) -> int:
    entries = collect_recent_entries(settings)
    print(f"Collected {len(entries)} candidate entries in window")

    notion = notion_client_from_settings(settings)
    supabase = get_supabase_client(settings)
    saved: list[SavedArticle] = []

    for entry in entries:
        try:
            if notion and not settings.dry_run and notion.url_exists(entry.url):
                print(f"[SKIP] Notion duplicate: {entry.title[:50]}")
                continue

            body = None
            if settings.llm_enabled:
                body = fetch_article_content(entry.url)
            text_for_llm = body or entry.rss_summary or entry.title

            analysis = analyze_article(
                settings=settings,
                title=entry.title,
                source=entry.source,
                body_text=text_for_llm,
                rss_summary=entry.rss_summary,
            )

            if settings.dry_run:
                saved.append(
                    SavedArticle(
                        source=entry.source,
                        url=entry.url,
                        title=entry.title,
                        summary_ja=analysis.summary_ja,
                        importance=analysis.importance,
                        category=analysis.category,
                        tags=analysis.tags,
                        published_at=entry.published_at,
                        fetched_at=datetime.now(timezone.utc),
                    )
                )
                continue

            article_row = SavedArticle(
                source=entry.source,
                url=entry.url,
                title=entry.title,
                summary_ja=analysis.summary_ja,
                importance=analysis.importance,
                category=analysis.category,
                tags=analysis.tags,
                published_at=entry.published_at,
                fetched_at=datetime.now(timezone.utc),
            )

            stored = False
            if notion:
                article = save_to_notion(
                    notion,
                    source=entry.source,
                    url=entry.url,
                    title=entry.title,
                    analysis=analysis,
                    published_at=entry.published_at,
                )
                if article:
                    saved.append(article)
                    stored = True

            if supabase:
                stored = (
                    save_to_supabase(
                        supabase,
                        source=entry.source,
                        url=entry.url,
                        title=entry.title,
                        analysis=analysis,
                        content_text=body,
                        rss_summary=entry.rss_summary,
                        published_at=entry.published_at,
                    )
                    or stored
                )

            if stored and not any(a.url == article_row.url for a in saved):
                saved.append(article_row)
            elif not notion and not supabase:
                saved.append(article_row)
        except Exception as exc:
            print(f"[ERROR] processing {entry.url}: {exc!r}")

    digest_md = build_digest_markdown(saved)
    print("\n" + "=" * 60)
    print(digest_md)
    print("=" * 60)

    if settings.dry_run:
        return 0

    if notion and settings.notion_parent_page_id and saved:
        title = digest_title()
        notion.create_digest_page(
            parent_page_id=settings.notion_parent_page_id,
            title=title,
            markdown_body=digest_md,
        )
        print(f"Notion digest page created: {title}")

    post_digest_webhook(settings, digest_md)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI news daily pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="APIキーなしでフィード収集し、ダイジェストを標準出力へ",
    )
    args = parser.parse_args(argv)
    settings = Settings.from_env(dry_run=args.dry_run)
    return run(settings)


if __name__ == "__main__":
    sys.exit(main())