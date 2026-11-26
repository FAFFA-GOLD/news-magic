"""HTTP helpers with retry/backoff for rate-limited APIs."""

from __future__ import annotations

import random
import time
from typing import Any

import requests

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_attempts: int = 6,
    **kwargs: Any,
) -> requests.Response:
    delay = 1.0
    last: requests.Response | None = None
    for attempt in range(max_attempts):
        last = session.request(method, url, **kwargs)
        if last.status_code not in RETRYABLE_STATUS:
            return last
        if attempt == max_attempts - 1:
            last.raise_for_status()
        retry_after = last.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            wait = float(retry_after)
        else:
            wait = delay + random.uniform(0, 0.5)
        print(f"[WARN] HTTP {last.status_code} on {url[:80]}… retry {attempt + 1}/{max_attempts - 1} in {wait:.1f}s")
        time.sleep(wait)
        delay = min(delay * 2, 60.0)
    assert last is not None
    return last