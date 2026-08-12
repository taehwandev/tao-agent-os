from __future__ import annotations

import io
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from unittest import mock


TOOL_DIR = Path(__file__).resolve().parents[1] / "scripts" / "figma-handoff"
sys.path.insert(0, str(TOOL_DIR))

from figma_api import FigmaApi, _PublicHttpsRedirectHandler, _SameOriginRedirectHandler, _retry_delay_seconds


class _Response:
    def __init__(self, payload: bytes, content_type: str | None = None) -> None:
        self._stream = io.BytesIO(payload)
        self.headers = Message()
        if content_type:
            self.headers["Content-Type"] = content_type

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _Opener:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, timeout: int) -> _Response:
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result  # type: ignore[return-value]


class FigmaApiSecurityTests(unittest.TestCase):
    def test_authenticated_redirect_rejects_cross_origin_before_forwarding_token(self) -> None:
        request = urllib.request.Request(
            "https://api.figma.com/v1/files/FILE",
            headers={"X-Figma-Token": "synthetic-marker"},
        )

        with self.assertRaises(RuntimeError):
            _SameOriginRedirectHandler().redirect_request(
                request,
                None,
                302,
                "Found",
                Message(),
                "https://attacker.example/collect",
            )

    def test_api_error_omits_response_body_and_token(self) -> None:
        headers = Message()
        error = urllib.error.HTTPError(
            "https://api.figma.com/v1/files/FILE",
            403,
            "Forbidden",
            headers,
            io.BytesIO(b"echoed-secret-response"),
        )
        opener = _Opener(error)
        with mock.patch("figma_api.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(RuntimeError) as raised:
                FigmaApi("synthetic-token", timeout=1, retries=0).get_json(
                    "https://api.figma.com/v1/files/FILE"
                )

        message = str(raised.exception)
        self.assertEqual(message, "Figma API failed (403).")
        self.assertNotIn("secret", message)
        self.assertNotIn("synthetic-token", message)

    def test_asset_download_rejects_non_https_and_private_targets(self) -> None:
        api = FigmaApi("synthetic-token", timeout=1, retries=0)
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "asset.svg"
            for url in (
                "file:///etc/passwd",
                "http://cdn.example/asset.svg",
                "https://localhost/asset.svg",
                "https://127.0.0.1/asset.svg",
                "https://169.254.169.254/asset.svg",
            ):
                with self.subTest(url=url), self.assertRaises(RuntimeError):
                    api.download(url, target, "svg")

    def test_asset_download_rejects_hostname_resolving_to_private_address(self) -> None:
        api = FigmaApi("synthetic-token", timeout=1, retries=0)
        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "figma_api.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.0.0.7", 443))],
        ):
            with self.assertRaises(RuntimeError):
                api.download(
                    "https://cdn.example/asset.svg",
                    Path(temporary) / "asset.svg",
                    "svg",
                )

    def test_asset_redirect_revalidates_public_target(self) -> None:
        request = urllib.request.Request("https://cdn.example/asset.svg")
        handler = _PublicHttpsRedirectHandler()
        with mock.patch(
            "figma_api.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
        ), self.assertRaises(RuntimeError):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                Message(),
                "https://redirect.example/private.svg",
            )

    def test_asset_download_is_streamed_bounded_and_never_authenticated(self) -> None:
        response = _Response(b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")
        opener = _Opener(response)
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "asset.svg"
            with mock.patch("figma_api.urllib.request.build_opener", return_value=opener), mock.patch(
                "figma_api.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
            ):
                FigmaApi("synthetic-token", timeout=1, retries=0).download(
                    "https://cdn.example/asset.svg?signature=synthetic",
                    target,
                    "svg",
                )

            self.assertTrue(target.read_bytes().startswith(b"<svg"))
            self.assertIsNone(opener.requests[0].get_header("X-Figma-Token"))

    def test_asset_download_rejects_oversize_or_wrong_signature_without_output(self) -> None:
        cases = (
            (_Response(b"0123456789", "image/png"), 8, "png"),
            (_Response(b"<script>alert(1)</script>", "image/svg+xml"), 1024, "svg"),
        )
        for response, limit, image_format in cases:
            with self.subTest(image_format=image_format), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / f"asset.{image_format}"
                with mock.patch(
                    "figma_api.urllib.request.build_opener",
                    return_value=_Opener(response),
                ), mock.patch(
                    "figma_api.socket.getaddrinfo",
                    return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
                ):
                    with self.assertRaises(RuntimeError):
                        FigmaApi(
                            "synthetic-token",
                            timeout=1,
                            retries=0,
                            max_download_bytes=limit,
                        ).download("https://cdn.example/asset", target, image_format)
                self.assertFalse(target.exists())

    def test_retry_after_is_capped(self) -> None:
        self.assertEqual(_retry_delay_seconds("999999", 0), 8.0)
        self.assertLessEqual(_retry_delay_seconds("Fri, 31 Dec 9999 23:59:59 GMT", 0), 8.0)
        self.assertEqual(_retry_delay_seconds("not-a-date", 1), 3.0)


if __name__ == "__main__":
    unittest.main()
