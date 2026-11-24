#!/usr/bin/env python3
"""Verify all feeds in feeds.yaml return RSS entries."""

from __future__ import annotations

import sys
from pathlib import Path

import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "feeds.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    feeds = data.get("feeds", [])
    failed = 0
    for item in feeds:
        name = item["source"]
        url = item["url"]
        try:
            r = requests.get(
                url,
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AI-News-Pipeline/2.0)"},
            )
            r.raise_for_status()
            d = feedparser.parse(r.content)
            n = len(d.entries)
            status = "OK" if n > 0 else "EMPTY"
            print(f"{status:5} {n:4}  {name}")
            if n == 0:
                failed += 1
        except Exception as exc:
            print(f"FAIL       {name}: {exc}")
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())