"""Parse and repair LLM JSON analysis output."""

from __future__ import annotations

import json
import re
from typing import Any


def strip_json_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _normalize_parsed(data: dict[str, Any]) -> dict[str, Any] | None:
    summary = str(data.get("summary_ja") or "").strip()
    if not summary:
        return None
    data["summary_ja"] = summary
    if "importance" not in data:
        data["importance"] = 3
    if not data.get("category"):
        data["category"] = "業界動向"
    if "tags" not in data:
        data["tags"] = []
    return data


def parse_llm_json(raw: str) -> dict[str, Any] | None:
    """Parse analysis JSON; try strict load, brace repair, then field extraction."""
    cleaned = strip_json_fence(raw)
    if not cleaned:
        return None
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return _normalize_parsed(data)
    except json.JSONDecodeError:
        pass

    repaired = _try_close_json(cleaned)
    if repaired is not None:
        return _normalize_parsed(repaired)

    extracted = extract_fields_lenient(cleaned)
    if extracted is not None:
        return _normalize_parsed(extracted)
    return None


def _try_close_json(text: str) -> dict[str, Any] | None:
    """Close unterminated strings/objects heuristically."""
    candidate = text
    for suffix in ('"', '"}', '"]', '"}]', '"}]}', '"}', '"} ]', "}", "]}"):
        attempt = candidate + suffix
        # balance braces
        open_c = attempt.count("{") - attempt.count("}")
        open_s = attempt.count("[") - attempt.count("]")
        attempt2 = attempt + ("]" * max(open_s, 0)) + ("}" * max(open_c, 0))
        try:
            data = json.loads(attempt2)
            if isinstance(data, dict) and data.get("summary_ja"):
                return data
        except json.JSONDecodeError:
            continue
    return None


def extract_fields_lenient(text: str) -> dict[str, Any] | None:
    summary_m = re.search(
        r'"summary_ja"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)',
        text,
        re.DOTALL,
    )
    if not summary_m:
        return None
    summary = summary_m.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
    if not summary:
        return None

    imp_m = re.search(r'"importance"\s*:\s*(\d+)', text)
    importance = int(imp_m.group(1)) if imp_m else 3

    cat_m = re.search(r'"category"\s*:\s*"([^"]+)"', text)
    category = cat_m.group(1).strip() if cat_m else "業界動向"

    tags: list[str] = []
    tags_m = re.search(r'"tags"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if tags_m:
        for t in re.findall(r'"([^"]+)"', tags_m.group(1)):
            if t.strip():
                tags.append(t.strip())

    return {
        "summary_ja": summary,
        "importance": importance,
        "category": category,
        "tags": tags,
    }