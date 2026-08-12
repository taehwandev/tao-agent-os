from __future__ import annotations

import datetime as dt
import email.utils
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


API_BASE_URL = "https://api.figma.com/v1"
USER_AGENT = "agent-os-figma-handoff/1.0"


def request_json(url: str, token: str, timeout: int, retries: int = 2) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "X-Figma-Token": token,
            "User-Agent": USER_AGENT,
        },
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            if error.code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(_retry_delay_seconds(error.headers.get("Retry-After"), attempt))
                continue
            raise RuntimeError(f"Figma API failed ({error.code}): {body}") from error
        except urllib.error.URLError as error:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RuntimeError(f"Figma API request failed: {error}") from error


def _retry_delay_seconds(retry_after: str | None, attempt: int) -> float:
    fallback = 1.5 * (attempt + 1)
    if not retry_after:
        return fallback
    try:
        return max(float(retry_after), fallback)
    except ValueError:
        pass

    try:
        retry_at = email.utils.parsedate_to_datetime(retry_after)
    except (TypeError, ValueError, IndexError, OverflowError):
        return fallback
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=dt.timezone.utc)
    delay = (retry_at - dt.datetime.now(dt.timezone.utc)).total_seconds()
    return max(delay, fallback)


def download_file(url: str, output_path: Path, timeout: int, retries: int = 2) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                output_path.write_bytes(response.read())
            return
        except (urllib.error.URLError, OSError) as error:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RuntimeError(
                f"Failed to download a Figma-rendered file ({type(error).__name__})."
            ) from error
