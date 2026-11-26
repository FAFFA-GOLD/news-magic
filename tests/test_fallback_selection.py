"""Tests for reanalyze fallback row selection."""

from __future__ import annotations

import unittest

from ai_news.llm import FALLBACK_TAG
from ai_news.notion_store import is_fallback_candidate


class TestFallbackSelection(unittest.TestCase):
    def test_tag_marker(self) -> None:
        self.assertTrue(
            is_fallback_candidate(tags=[FALLBACK_TAG], importance=4, category="研究")
        )

    def test_legacy_fallback_combo(self) -> None:
        self.assertTrue(
            is_fallback_candidate(tags=[], importance=3, category="業界動向")
        )

    def test_reanalyzed_row_not_selected(self) -> None:
        self.assertFalse(
            is_fallback_candidate(tags=[], importance=4, category="業界動向")
        )
        self.assertFalse(
            is_fallback_candidate(tags=["LLM"], importance=5, category="業界動向")
        )
        self.assertFalse(
            is_fallback_candidate(tags=[], importance=3, category="新モデル")
        )


if __name__ == "__main__":
    unittest.main()