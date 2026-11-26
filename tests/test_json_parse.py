"""Tests for truncated LLM JSON repair."""

from __future__ import annotations

import unittest

from ai_news.json_parse import extract_fields_lenient, parse_llm_json


class TestJsonParse(unittest.TestCase):
    def test_valid_json(self) -> None:
        raw = (
            '{"summary_ja": "テスト要約です。", "importance": 4, '
            '"category": "新モデル", "tags": ["LLM"]}'
        )
        data = parse_llm_json(raw)
        assert data is not None
        self.assertEqual(data["summary_ja"], "テスト要約です。")
        self.assertEqual(data["importance"], 4)

    def test_unterminated_summary_string(self) -> None:
        raw = (
            '{"summary_ja": "これは途中で切れた日本語要約の文'
        )
        data = parse_llm_json(raw)
        assert data is not None
        self.assertIn("これは途中", data["summary_ja"])
        self.assertEqual(data["importance"], 3)

    def test_truncated_with_partial_fields(self) -> None:
        raw = (
            '{"summary_ja": "OpenAIが新モデルを発表。", "importance": 5, '
            '"category": "新モデル", "tags": ["OpenAI", "GPT'
        )
        data = extract_fields_lenient(raw)
        assert data is not None
        self.assertEqual(data["category"], "新モデル")
        self.assertGreaterEqual(data["importance"], 1)


if __name__ == "__main__":
    unittest.main()