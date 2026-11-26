"""Discover and select a Gemini model for generateContent."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import requests

from ai_news.config import Settings
from ai_news.http_retry import request_with_retry

MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Prefer stable flash; deprioritize these name fragments.
_DEPRIORITIZE = (
    "preview",
    "exp",
    "experimental",
    "thinking",
    "image",
    "tts",
    "embedding",
    "aqa",
    "nano",
    "robotics",
    "computer-use",
)


class GeminiSetupError(RuntimeError):
    """Gemini API key cannot list or resolve a usable model."""


class LlmClientError(RuntimeError):
    """Non-retryable 4xx from the LLM API (excluding 429)."""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"LLM client error {status_code}")
        self.status_code = status_code
        self.body = body


@dataclass
class LlmProbeState:
    """Abort normal runs when the first probe window is all client errors."""

    max_probe: int = 5
    client_errors: int = 0
    successes: int = 0

    def record_client_error(self) -> None:
        self.client_errors += 1

    def record_success(self) -> None:
        self.successes += 1

    def should_abort(self) -> bool:
        return (
            self.successes == 0
            and self.client_errors >= self.max_probe
        )


@dataclass
class GeminiRuntime:
    api_key: str
    configured_model: str | None
    resolved_model: str = ""
    catalog_ids: list[str] = field(default_factory=list)
    _retried_404: bool = False

    @property
    def model_from_env(self) -> bool:
        return bool(self.configured_model)


def model_id_from_api_name(name: str) -> str:
    return name.split("/")[-1] if "/" in name else name


def rank_model(model_id: str) -> tuple[float, int]:
    """Higher is better. Prefer newer gemini *flash* without preview/exp/thinking."""
    lower = model_id.lower()
    score = 0.0
    if "gemini" not in lower:
        score -= 50
    if "flash" in lower:
        score += 40
    elif "pro" in lower:
        score += 10
    for frag in _DEPRIORITIZE:
        if frag in lower:
            score -= 25
    if "lite" in lower:
        score -= 8
    vm = re.search(r"gemini-(\d+)\.(\d+)", lower)
    if vm:
        score += int(vm.group(1)) * 10 + int(vm.group(2))
    return (score, 1 if "flash" in lower else 0)


def pick_best_generate_content_model(models: list[dict[str, Any]]) -> str:
    candidates: list[str] = []
    for item in models:
        methods = item.get("supportedGenerationMethods") or []
        if "generateContent" not in methods:
            continue
        mid = model_id_from_api_name(str(item.get("name", "")))
        if mid:
            candidates.append(mid)
    if not candidates:
        raise GeminiSetupError("No models with generateContent in API list")

    flash = [m for m in candidates if "flash" in m.lower()]
    pool = flash if flash else candidates
    pool.sort(key=rank_model, reverse=True)
    return pool[0]


def fetch_model_catalog(api_key: str) -> list[dict[str, Any]]:
    session = requests.Session()
    models: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, str] = {"key": api_key, "pageSize": "100"}
        if page_token:
            params["pageToken"] = page_token
        resp = request_with_retry(session, "GET", MODELS_URL, params=params, timeout=60)
        if not resp.ok:
            raise GeminiSetupError(
                f"ListModels failed HTTP {resp.status_code}: {resp.text[:2000]}"
            )
        payload = resp.json()
        models.extend(payload.get("models", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return models


def catalog_generate_content_ids(models: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for item in models:
        methods = item.get("supportedGenerationMethods") or []
        if "generateContent" in methods:
            mid = model_id_from_api_name(str(item.get("name", "")))
            if mid:
                ids.append(mid)
    return ids


def prepare_gemini(settings: Settings) -> GeminiRuntime:
    if not settings.gemini_api_key:
        raise GeminiSetupError("GEMINI_API_KEY is not set")

    runtime = GeminiRuntime(
        api_key=settings.gemini_api_key,
        configured_model=settings.gemini_model,
    )
    models = fetch_model_catalog(settings.gemini_api_key)
    runtime.catalog_ids = catalog_generate_content_ids(models)

    if not runtime.catalog_ids:
        raise GeminiSetupError("No generateContent models available for this API key")

    if runtime.configured_model:
        runtime.resolved_model = runtime.configured_model
        print(f"Gemini model (from GEMINI_MODEL): {runtime.resolved_model}")
    else:
        runtime.resolved_model = pick_best_generate_content_model(models)
        print(f"Gemini model (auto-selected): {runtime.resolved_model}")

    return runtime


def reselect_after_404(runtime: GeminiRuntime) -> str | None:
    if runtime._retried_404:
        return None
    runtime._retried_404 = True
    exclude = {runtime.resolved_model}
    remaining = [m for m in runtime.catalog_ids if m not in exclude]
    if not remaining:
        remaining = runtime.catalog_ids
    if not remaining:
        return None
    remaining.sort(key=rank_model, reverse=True)
    runtime.resolved_model = remaining[0]
    print(f"Gemini model (re-selected after 404): {runtime.resolved_model}")
    return runtime.resolved_model