"""Environment and runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FEEDS_PATH = REPO_ROOT / "feeds.yaml"

# Used only when GEMINI_MODEL is explicitly set; otherwise auto-selected at runtime.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

CATEGORIES = [
    "新モデル",
    "ツール・サービス",
    "お得情報・料金",
    "研究",
    "業界動向",
    "国内",
]

CONTENT_MAX_CHARS = 6000
SUMMARY_INPUT_MAX_CHARS = 2800
DEFAULT_GEMINI_MAX_OUTPUT_TOKENS = 8192


def _env_str(key: str, default: str) -> str:
    value = os.environ.get(key)
    if value is None or not str(value).strip():
        return default
    return str(value).strip()


def _env_optional(key: str) -> str | None:
    value = os.environ.get(key)
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


@dataclass(frozen=True)
class Settings:
    feeds_path: Path
    dry_run: bool
    reanalyze_fallback: bool
    cleanup_text: bool
    hours_window: int
    max_entries_per_feed: int
    gemini_api_key: str | None
    gemini_model: str | None
    gemini_pace_seconds: float
    gemini_max_output_tokens: int
    gemini_summary_input_max_chars: int
    openai_api_key: str | None
    openai_base_url: str
    openai_model: str
    notion_token: str | None
    notion_database_id: str | None
    notion_parent_page_id: str | None
    digest_webhook_url: str | None
    notion_dedupe_days: int

    @classmethod
    def from_env(
        cls,
        *,
        dry_run: bool = False,
        reanalyze_fallback: bool = False,
        cleanup_text: bool = False,
    ) -> Settings:
        return cls(
            feeds_path=Path(_env_str("FEEDS_PATH", str(DEFAULT_FEEDS_PATH))),
            dry_run=dry_run or _env_str("DRY_RUN", "").lower() in ("1", "true", "yes"),
            reanalyze_fallback=reanalyze_fallback
            or _env_str("REANALYZE_FALLBACK", "").lower() in ("1", "true", "yes"),
            cleanup_text=cleanup_text
            or _env_str("CLEANUP_TEXT", "").lower() in ("1", "true", "yes"),
            hours_window=int(_env_str("HOURS_WINDOW", "24")),
            max_entries_per_feed=int(_env_str("MAX_ENTRIES_PER_FEED", "25")),
            gemini_api_key=_env_optional("GEMINI_API_KEY"),
            gemini_model=_env_optional("GEMINI_MODEL"),
            gemini_pace_seconds=float(_env_str("GEMINI_PACE_SECONDS", "4.0")),
            gemini_max_output_tokens=int(
                _env_str("GEMINI_MAX_OUTPUT_TOKENS", str(DEFAULT_GEMINI_MAX_OUTPUT_TOKENS))
            ),
            gemini_summary_input_max_chars=int(
                _env_str("GEMINI_SUMMARY_INPUT_MAX_CHARS", str(SUMMARY_INPUT_MAX_CHARS))
            ),
            openai_api_key=_env_optional("OPENAI_API_KEY"),
            openai_base_url=_env_str("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).rstrip(
                "/"
            ),
            openai_model=_env_str("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            notion_token=_env_optional("NOTION_TOKEN"),
            notion_database_id=_env_optional("NOTION_DATABASE_ID"),
            notion_parent_page_id=_env_optional("NOTION_PARENT_PAGE_ID"),
            digest_webhook_url=_env_optional("DIGEST_WEBHOOK_URL"),
            notion_dedupe_days=int(_env_str("NOTION_DEDUPE_DAYS", "14")),
        )

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key or self.openai_api_key)

    @property
    def notion_enabled(self) -> bool:
        return bool(self.notion_token and self.notion_database_id)