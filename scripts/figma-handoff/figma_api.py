from __future__ import annotations

import datetime as dt
import email.utils
import ipaddress
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


API_BASE_URL = "https://api.figma.com/v1"
USER_AGENT = "tao-agent-os-figma-handoff/1.0"
_API_ORIGIN = "https://api.figma.com"
_MAX_API_BYTES = 16 * 1024 * 1024
_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
_MAX_RETRY_DELAY_SECONDS = 8.0
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_LOCAL_HOST_SUFFIXES = (".localhost", ".local", ".internal")


class FigmaApi:
    """Authenticated Figma JSON access and isolated unsigned asset downloads."""

    def __init__(
        self,
        token: str,
        timeout: int,
        retries: int = 2,
        max_download_bytes: int = _MAX_DOWNLOAD_BYTES,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if retries < 0:
            raise ValueError("retries must not be negative")
        if max_download_bytes <= 0:
            raise ValueError("max_download_bytes must be greater than zero")
        self._token = token
        self._timeout = timeout
        self._retries = retries
        self._max_download_bytes = max_download_bytes

    def get_json(self, url: str) -> dict[str, Any]:
        _validate_api_url(url)
        request = urllib.request.Request(
            url,
            headers={"X-Figma-Token": self._token, "User-Agent": USER_AGENT},
        )
        opener = urllib.request.build_opener(_SameOriginRedirectHandler())
        for attempt in range(self._retries + 1):
            try:
                with opener.open(request, timeout=self._timeout) as response:
                    payload = _read_limited(response, _MAX_API_BYTES)
                parsed = json.loads(payload.decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise RuntimeError("Figma API returned a non-object JSON response.")
                return parsed
            except urllib.error.HTTPError as error:
                if error.code in _RETRYABLE_STATUS and attempt < self._retries:
                    time.sleep(_retry_delay_seconds(_header(error.headers, "Retry-After"), attempt))
                    continue
                raise RuntimeError(f"Figma API failed ({error.code}).") from error
            except urllib.error.URLError as error:
                if attempt < self._retries:
                    time.sleep(_retry_delay_seconds(None, attempt))
                    continue
                raise RuntimeError("Figma API request failed (network error).") from error
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RuntimeError("Figma API returned invalid JSON.") from error

        raise AssertionError("unreachable")

    def download(self, url: str, output_path: Path, expected_format: str | None = None) -> None:
        _validate_public_https_url(url)
        image_format = (expected_format or output_path.suffix.lstrip(".")).lower()
        if image_format == "jpeg":
            image_format = "jpg"
        if image_format not in {"png", "jpg", "svg", "pdf"}:
            raise RuntimeError("Unsupported rendered asset format.")

        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        opener = urllib.request.build_opener(_PublicHttpsRedirectHandler())
        for attempt in range(self._retries + 1):
            try:
                with opener.open(request, timeout=self._timeout) as response:
                    _validate_content_length(response, self._max_download_bytes)
                    _validate_content_type(response, image_format)
                    _stream_validated_file(
                        response,
                        output_path,
                        image_format,
                        self._max_download_bytes,
                    )
                return
            except urllib.error.HTTPError as error:
                if error.code in _RETRYABLE_STATUS and attempt < self._retries:
                    time.sleep(_retry_delay_seconds(_header(error.headers, "Retry-After"), attempt))
                    continue
                raise RuntimeError(f"Figma asset download failed ({error.code}).") from error
            except urllib.error.URLError as error:
                if attempt < self._retries:
                    time.sleep(_retry_delay_seconds(None, attempt))
                    continue
                raise RuntimeError("Figma asset download failed (network error).") from error
            except OSError as error:
                raise RuntimeError("Figma asset download failed (filesystem error).") from error


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        _validate_api_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _PublicHttpsRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        _validate_public_https_url(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("X-Figma-Token")
        return redirected


def _validate_api_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != "https" or _origin(parsed) != _API_ORIGIN:
        raise RuntimeError("Figma API URL must use the trusted HTTPS origin.")


def _validate_public_https_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password:
        raise RuntimeError("Figma asset URL must be public HTTPS.")
    if host == "localhost" or host.endswith(_LOCAL_HOST_SUFFIXES):
        raise RuntimeError("Figma asset URL must not target a local host.")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(sockaddr[0])
                for _, _, _, _, sockaddr in socket.getaddrinfo(
                    host, parsed.port or 443, type=socket.SOCK_STREAM
                )
            }
        except (OSError, ValueError) as error:
            raise RuntimeError("Figma asset host could not be resolved safely.") from error
        if not addresses or any(not candidate.is_global for candidate in addresses):
            raise RuntimeError("Figma asset URL must not target a private address.")
        return
    if not address.is_global:
        raise RuntimeError("Figma asset URL must not target a private address.")


def _origin(parsed: urllib.parse.SplitResult) -> str:
    host = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port
    if port in (None, 443):
        return f"https://{host}"
    return f"https://{host}:{port}"


def _retry_delay_seconds(retry_after: str | None, attempt: int) -> float:
    fallback = min(1.5 * (attempt + 1), _MAX_RETRY_DELAY_SECONDS)
    delay = fallback
    if retry_after:
        try:
            delay = max(float(retry_after), fallback)
        except ValueError:
            try:
                retry_at = email.utils.parsedate_to_datetime(retry_after)
            except (TypeError, ValueError, IndexError, OverflowError):
                retry_at = None
            if retry_at is not None:
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=dt.timezone.utc)
                delay = max(
                    (retry_at - dt.datetime.now(dt.timezone.utc)).total_seconds(),
                    fallback,
                )
    return max(0.0, min(delay, _MAX_RETRY_DELAY_SECONDS))


def _read_limited(response: Any, limit: int) -> bytes:
    payload = response.read(limit + 1)
    if len(payload) > limit:
        raise RuntimeError("Figma response exceeded the configured size limit.")
    return payload


def _header(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    value = headers.get(name)
    return str(value) if value is not None else None


def _validate_content_length(response: Any, limit: int) -> None:
    value = _header(getattr(response, "headers", None), "Content-Length")
    if value is None:
        return
    try:
        length = int(value)
    except ValueError as error:
        raise RuntimeError("Figma asset returned an invalid Content-Length.") from error
    if length < 0 or length > limit:
        raise RuntimeError("Figma asset exceeded the configured size limit.")


def _validate_content_type(response: Any, image_format: str) -> None:
    value = _header(getattr(response, "headers", None), "Content-Type")
    if not value:
        return
    media_type = value.split(";", 1)[0].strip().lower()
    allowed = {
        "png": {"image/png", "application/octet-stream"},
        "jpg": {"image/jpeg", "application/octet-stream"},
        "svg": {"image/svg+xml", "text/xml", "application/xml", "application/octet-stream"},
        "pdf": {"application/pdf", "application/octet-stream"},
    }[image_format]
    if media_type not in allowed:
        raise RuntimeError("Figma asset returned an unexpected content type.")


def _stream_validated_file(response: Any, output_path: Path, image_format: str, limit: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.part")
    total = 0
    prefix = bytearray()
    try:
        with temporary.open("wb") as handle:
            while True:
                chunk = response.read(min(64 * 1024, limit - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise RuntimeError("Figma asset exceeded the configured size limit.")
                if len(prefix) < 512:
                    prefix.extend(chunk[: 512 - len(prefix)])
                handle.write(chunk)
        if total == 0 or not _matches_signature(bytes(prefix), image_format):
            raise RuntimeError("Figma asset content did not match the requested format.")
        temporary.replace(output_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _matches_signature(prefix: bytes, image_format: str) -> bool:
    if image_format == "png":
        return prefix.startswith(b"\x89PNG\r\n\x1a\n")
    if image_format == "jpg":
        return prefix.startswith(b"\xff\xd8\xff")
    if image_format == "pdf":
        return prefix.startswith(b"%PDF-")
    text = prefix.lstrip(b"\xef\xbb\xbf\x00\t\r\n ").lower()
    return text.startswith(b"<svg") or (text.startswith(b"<?xml") and b"<svg" in text)
