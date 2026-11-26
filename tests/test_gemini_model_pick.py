"""Tests for Gemini model auto-selection."""

from __future__ import annotations

import unittest

from ai_news.gemini_models import pick_best_generate_content_model, rank_model


def _model(name: str, methods: list[str]) -> dict:
    return {"name": f"models/{name}", "supportedGenerationMethods": methods}


class TestGeminiModelPick(unittest.TestCase):
    def test_prefers_stable_flash_over_preview(self) -> None:
        models = [
            _model("gemini-2.5-flash", ["generateContent"]),
            _model("gemini-2.5-flash-preview-05-20", ["generateContent"]),
            _model("gemini-2.0-flash", ["generateContent"]),
        ]
        self.assertEqual(pick_best_generate_content_model(models), "gemini-2.5-flash")

    def test_skips_non_generate_content(self) -> None:
        models = [
            _model("gemini-embedding-001", ["embedContent"]),
            _model("gemini-2.0-flash", ["generateContent"]),
        ]
        self.assertEqual(pick_best_generate_content_model(models), "gemini-2.0-flash")

    def test_rank_orders_newer_flash_higher(self) -> None:
        self.assertGreater(
            rank_model("gemini-2.5-flash")[0],
            rank_model("gemini-2.0-flash")[0],
        )


if __name__ == "__main__":
    unittest.main()