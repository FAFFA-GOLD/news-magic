"""Main collection pipeline."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from ai_news.config import Settings
from ai_news.content import fetch_article_content
from ai_news.digest import build_digest_markdown, digest_title, post_digest_webhook
from ai_news.feeds import collect_recent_entries
from ai_news.llm import analyze_article, tags_for_storage
from ai_news.notion_store import (
    SavedArticle,
    notion_client_from_settings,
    publish_digest,
    save_to_notion,
)


@dataclass
class RunStats:
    candidates: int = 0
    saved: int = 0
    llm_attempts: int = 0
    llm_failures: int = 0
    reanalyzed: int = 0


def _record_llm(settings: Settings, stats: RunStats, analysis) -> None:
    if not settings.llm_enabled:
        return
    stats.llm_attempts += 1
    if analysis.used_fallback:
        stats.llm_failures += 1


def _finalize_exit(settings: Settings, stats: RunStats) -> int:
    if settings.dry_run:
        return 0

    if settings.reanalyze_fallback:
        if settings.llm_enabled and stats.reanalyzed == 0 and stats.llm_attempts > 0:
            print("[ERROR] reanalyze: no articles updated")
            return 1
        if settings.llm_enabled and stats.llm_attempts > 0:
            if stats.llm_failures / stats.llm_attempts >= 0.9:
                print("[ERROR] reanalyze: LLM failed for nearly all articles")
                return 1
        return 0

    if settings.notion_enabled and stats.candidates > 0 and stats.saved == 0:
        print("[ERROR] 0 articles saved despite candidates (check Gemini / Notion)")
        return 1

    if settings.llm_enabled and stats.llm_attempts > 0:
        ratio = stats.llm_failures / stats.llm_attempts
        if ratio >= 0.9:
            print(
                f"[ERROR] LLM summarization failed for {stats.llm_failures}/"
                f"{stats.llm_attempts} articles"
            )
            return 1

    return 0


def run_collect(settings: Settings) -> int:
    stats = RunStats()
    entries = collect_recent_entries(settings)
    stats.candidates = len(entries)
    print(f"Collected {len(entries)} candidate entries in window")

    notion = notion_client_from_settings(settings)
    existing_urls: set[str] = set()
    if notion and not settings.dry_run:
        existing_urls = notion.preload_recent_urls(settings.notion_dedupe_days)

    saved: list[SavedArticle] = []

    for entry in entries:
        try:
            if not settings.dry_run and entry.url in existing_urls:
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
            _record_llm(settings, stats, analysis)

            if settings.dry_run:
                saved.append(
                    SavedArticle(
                        source=entry.source,
                        url=entry.url,
                        title=entry.title,
                        summary_ja=analysis.summary_ja,
                        importance=analysis.importance,
                        category=analysis.category,
                        tags=tags_for_storage(analysis),
                        published_at=entry.published_at,
                        fetched_at=datetime.now(timezone.utc),
                    )
                )
                continue

            if notion:
                article = save_to_notion(
                    notion,
                    source=entry.source,
                    url=entry.url,
                    title=entry.title,
                    analysis=analysis,
                    published_at=entry.published_at,
                    existing_urls=existing_urls,
                )
                if article:
                    saved.append(article)
                    stats.saved += 1
        except Exception as exc:
            print(f"[ERROR] processing {entry.url}: {exc!r}")

    digest_md = build_digest_markdown(saved)
    print("\n" + "=" * 60)
    print(digest_md)
    print("=" * 60)

    if settings.dry_run:
        return 0

    if notion and settings.notion_parent_page_id and saved:
        notion.upsert_digest_page(
            parent_page_id=settings.notion_parent_page_id,
            title=digest_title(),
            markdown_body=digest_md,
        )
    post_digest_webhook(settings, digest_md)

    return _finalize_exit(settings, stats)


def run_reanalyze(settings: Settings) -> int:
    stats = RunStats()
    notion = notion_client_from_settings(settings)
    if not notion:
        print("[ERROR] reanalyze requires Notion configuration")
        return 1

    if not settings.llm_enabled:
        print("[ERROR] reanalyze requires GEMINI_API_KEY or OPENAI_API_KEY")
        return 1

    rows = notion.query_fallback_articles(days=settings.notion_dedupe_days)
    print(f"Found {len(rows)} fallback candidate rows")
    stats.candidates = len(rows)

    for row in rows:
        try:
            body = fetch_article_content(row.url)
            text = body or row.summary_ja or row.title
            analysis = analyze_article(
                settings=settings,
                title=row.title,
                source=row.source or "再分析",
                body_text=text,
                rss_summary=row.summary_ja,
            )
            _record_llm(settings, stats, analysis)
            if analysis.used_fallback:
                continue
            notion.update_article_page(row.page_id, analysis)
            stats.reanalyzed += 1
            stats.saved += 1
            print(f"Reanalyzed: {row.title[:60]}")
        except Exception as exc:
            print(f"[ERROR] reanalyze {row.url}: {exc!r}")

    if settings.notion_parent_page_id:
        publish_digest(
            settings,
            notion,
            [],
            from_notion_hours=settings.hours_window,
        )
    else:
        articles = notion.query_articles_since_hours(settings.hours_window)
        digest_md = build_digest_markdown(articles)
        print("\n" + "=" * 60)
        print(digest_md)
        print("=" * 60)
        post_digest_webhook(settings, digest_md)

    return _finalize_exit(settings, stats)


def run(settings: Settings) -> int:
    if settings.reanalyze_fallback:
        return run_reanalyze(settings)
    return run_collect(settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI news daily pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="APIキーなしでフィード収集し、ダイジェストを標準出力へ",
    )
    parser.add_argument(
        "--reanalyze-fallback",
        action="store_true",
        help="Notion上の要約未処理行を Gemini で再要約しダイジェストを更新",
    )
    args = parser.parse_args(argv)
    settings = Settings.from_env(
        dry_run=args.dry_run,
        reanalyze_fallback=args.reanalyze_fallback,
    )
    return run(settings)


if __name__ == "__main__":
    sys.exit(main())