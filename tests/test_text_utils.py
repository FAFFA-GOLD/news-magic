"""Tests for RSS text cleanup."""

from __future__ import annotations

import unittest

from ai_news.text_utils import (
    clean_rss_text,
    normalize_feed_title,
    normalize_stored_text,
)


class TestTextUtils(unittest.TestCase):
    def test_strips_nbsp_entity(self) -> None:
        self.assertEqual(clean_rss_text("Hello&nbsp;world"), "Hello world")

    def test_strips_nbsp_and_dash_anthropic(self) -> None:
        self.assertEqual(
            normalize_stored_text("&nbsp;&nbsp; Anthropic"),
            "Anthropic",
        )

    def test_strips_leading_dash(self) -> None:
        self.assertEqual(normalize_stored_text("- Anthropic"), "Anthropic")

    def test_google_news_title_unchanged_when_long(self) -> None:
        class E:
            title = "OpenAI ships GPT-5 - TechCrunch"
            summary = ""

        t = normalize_feed_title("- stub", "Anthropic (Google News)", E())
        self.assertIn("GPT-5", t)


if __name__ == "__main__":
    unittest.main()