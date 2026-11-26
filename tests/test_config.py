"""Unit tests for configuration parsing."""

from __future__ import annotations

import os
import unittest


class TestSettings(unittest.TestCase):
    def test_empty_optional_vars_use_defaults(self) -> None:
        from ai_news.config import DEFAULT_GEMINI_MODEL, Settings

        env = {
            "GEMINI_MODEL": "",
            "OPENAI_BASE_URL": "",
            "OPENAI_MODEL": "  ",
            "GEMINI_API_KEY": "",
        }
        old = {k: os.environ.get(k) for k in env}
        try:
            os.environ.update(env)
            settings = Settings.from_env()
            self.assertEqual(settings.gemini_model, DEFAULT_GEMINI_MODEL)
            self.assertEqual(settings.openai_base_url, "https://api.openai.com/v1")
            self.assertEqual(settings.openai_model, "gpt-4o-mini")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()