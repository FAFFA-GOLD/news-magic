"""Tests for RSS text cleanup."""

from __future__ import annotations

import unittest

from ai_news.text_utils import clean_rss_text


class TestTextUtils(unittest.TestCase):
    def test_strips_nbsp_entity(self) -> None:
        self.assertEqual(clean_rss_text("Hello&nbsp;world"), "Hello world")

    def test_strips_numeric_nbsp(self) -> None:
        self.assertEqual(clean_rss_text("A\u00a0B"), "A B")


if __name__ == "__main__":
    unittest.main()