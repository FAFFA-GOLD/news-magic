"""Environment and runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FEEDS_PATH = REPO_ROOT / "feeds.yaml"

CATEGORIES = [
    "新モデル",
    "ツール・サービス",
    "お得情報・料金",
    "研究",
    "業界動向",
    "国内",
]

CONTENT_MAX_CHARS = 6000
SUMMARY_INPUT_MAX_CHARS = 4000


@dataclass(frozen=True)
class Settings:
    feeds_path: Path
    dry_run: bool
    hours_window: int
    max_entries_per_feed: int
    gemini_api_key: str | None
    gemini_model: str
    openai_api_key: str | None
    openai_base_url: str
    openai_model: str
    notion_token: str | None
    notion_database_id: str | None
    notion_parent_page_id: str | None
    digest_webhook_url: str | None
    supabase_url: str | None
    supabase_service_role_key: str | None

    @classmethod
    def from_env(cls, *, dry_run: bool = False) -> Settings:
        return cls(
            feeds_path=Path(os.environ.get("FEEDS_PATH", str(DEFAULT_FEEDS_PATH))),
            dry_run=dry_run or os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"),
            hours_window=int(os.environ.get("HOURS_WINDOW", "24")),
            max_entries_per_feed=int(os.environ.get("MAX_ENTRIES_PER_FEED", "25")),
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
            openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
            openai_base_url=os.environ.get(
                "OPENAI_BASE_URL", "https://api.openai.com/v1"
            ).rstrip("/"),
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            notion_token=os.environ.get("NOTION_TOKEN") or None,
            notion_database_id=os.environ.get("NOTION_DATABASE_ID") or None,
            notion_parent_page_id=os.environ.get("NOTION_PARENT_PAGE_ID") or None,
            digest_webhook_url=os.environ.get("DIGEST_WEBHOOK_URL") or None,
            supabase_url=os.environ.get("SUPABASE_URL") or None,
            supabase_service_role_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or None,
        )

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key or self.openai_api_key)

    @property
    def notion_enabled(self) -> bool:
        return bool(self.notion_token and self.notion_database_id)

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)