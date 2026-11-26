"""Tests for Notion digest block building."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ai_news.digest_blocks import (
    DIGEST_CAP_PER_CATEGORY,
    FALLBACK_SECTION_CAP,
    build_notion_digest_blocks,
)
from ai_news.llm import FALLBACK_TAG
from ai_news.notion_store import SavedArticle


def _art(
    title: str,
    *,
    cat: str = "業界動向",
    imp: int = 3,
    tags: list[str] | None = None,
    url: str = "https://example.com/a",
) -> SavedArticle:
    return SavedArticle(
        source="Test",
        url=url,
        title=title,
        summary_ja="要約テキスト。",
        importance=imp,
        category=cat,
        tags=tags or [],
        published_at=None,
        fetched_at=datetime.now(timezone.utc),
    )


class TestDigestBlocks(unittest.TestCase):
    def test_heading_and_bullet_shape(self) -> None:
        articles = [_art("記事A", cat="新モデル", imp=5, url="https://ex/a")]
        blocks = build_notion_digest_blocks(articles)
        types = [b["type"] for b in blocks]
        self.assertIn("heading_2", types)
        bullet = next(b for b in blocks if b["type"] == "bulleted_list_item")
        rt = bullet["bulleted_list_item"]["rich_text"]
        self.assertTrue(rt[0]["annotations"]["bold"])
        self.assertIn("link", rt[1]["text"])

    def test_category_cap(self) -> None:
        articles = [
            _art(f"n{i}", cat="国内", imp=i, url=f"https://ex/{i}")
            for i in range(15)
        ]
        blocks = build_notion_digest_blocks(articles)
        bullets = [b for b in blocks if b["type"] == "bulleted_list_item"]
        self.assertEqual(len(bullets), DIGEST_CAP_PER_CATEGORY)
        self.assertTrue(any("ほか" in b["paragraph"]["rich_text"][0]["text"]["content"] for b in blocks if b["type"] == "paragraph"))

    def test_fallback_section_separate(self) -> None:
        main = _art("本体", cat="研究")
        fb = _art("未処理", tags=[FALLBACK_TAG])
        blocks = build_notion_digest_blocks([main, fb])
        headings = [b["heading_2"]["rich_text"][0]["text"]["content"] for b in blocks if b["type"] == "heading_2"]
        self.assertIn("研究", headings)
        self.assertIn("要約未処理", headings)
        fb_bullets = [
            b
            for b in blocks
            if b["type"] == "bulleted_list_item"
            and "要約未処理" not in str(b)
        ]
        self.assertGreaterEqual(len(fb_bullets), 1)

    def test_fallback_cap(self) -> None:
        articles = [
            _art(f"fb{i}", tags=[FALLBACK_TAG], url=f"https://ex/f{i}")
            for i in range(8)
        ]
        blocks = build_notion_digest_blocks(articles)
        self.assertEqual(
            sum(1 for b in blocks if b["type"] == "bulleted_list_item"),
            FALLBACK_SECTION_CAP,
        )


if __name__ == "__main__":
    unittest.main()