"""Tests for early LLM abort probe."""

from __future__ import annotations

import unittest

from ai_news.gemini_models import LlmProbeState


class TestLlmProbe(unittest.TestCase):
    def test_aborts_after_five_client_errors_no_success(self) -> None:
        probe = LlmProbeState(max_probe=5)
        for _ in range(4):
            probe.record_client_error()
            self.assertFalse(probe.should_abort())
        probe.record_client_error()
        self.assertTrue(probe.should_abort())

    def test_success_resets_abort(self) -> None:
        probe = LlmProbeState(max_probe=5)
        for _ in range(5):
            probe.record_client_error()
        probe.record_success()
        self.assertFalse(probe.should_abort())


if __name__ == "__main__":
    unittest.main()