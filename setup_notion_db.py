#!/usr/bin/env python3
"""Create the Notion articles database under a parent page."""

from __future__ import annotations

import os
import sys

from ai_news.notion_store import create_database


def main() -> int:
    token = os.environ.get("NOTION_TOKEN")
    parent = os.environ.get("NOTION_PARENT_PAGE_ID")
    if not token or not parent:
        print(
            "NOTION_TOKEN と NOTION_PARENT_PAGE_ID を設定してください。",
            file=sys.stderr,
        )
        return 1

    title = os.environ.get("NOTION_DATABASE_TITLE", "AIニュース記事")
    db = create_database(token, parent, title=title)
    db_id = db.get("id")
    print("データベースを作成しました。")
    print(f"  NOTION_DATABASE_ID={db_id}")
    print("GitHub Secrets の NOTION_DATABASE_ID に上記を設定してください。")
    print("親ページでインテグレーションを「接続」済みか確認してください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())