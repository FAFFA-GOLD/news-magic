"""Tests for Notion child page title parsing."""

from __future__ import annotations

import unittest

from ai_news.notion_store import parse_child_page_title


class TestNotionTitle(unittest.TestCase):
    def test_plain_string_title(self) -> None:
        self.assertEqual(
            parse_child_page_title("AIダイジェスト 2026-11-26"),
            "AIダイジェスト 2026-11-26",
        )

    def test_rich_text_title(self) -> None:
        title = [{"plain_text": "AIダイジェスト ", "type": "text"}, {"plain_text": "2026-11-26", "type": "text"}]
        self.assertEqual(parse_child_page_title(title), "AIダイジェスト 2026-11-26")

    def test_find_first_match_semantics(self) -> None:
        blocks = [
            {"type": "child_page", "id": "a", "child_page": {"title": "other"}},
            {"type": "child_page", "id": "b", "child_page": {"title": "AIダイジェスト 2026-11-26"}},
        ]
        target = "AIダイジェスト 2026-11-26"
        found = None
        for block in blocks:
            if block.get("type") != "child_page":
                continue
            if parse_child_page_title(block["child_page"]["title"]) == target:
                found = block["id"]
                break
        self.assertEqual(found, "b")


if __name__ == "__main__":
    unittest.main()