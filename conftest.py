"""Root conftest — project-wide test guarantees.

Prompt 2 ground rule 1: this suite must run fully offline. The socket guard
below is autouse for EVERY test under the project root; there is deliberately
no opt-out marker. Tests that need network fixtures must mock the fetch layer.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

_ORIGINAL_SOCKET = socket.socket


class _BlockedCurlSession:
    """Blocks curl_cffi Session (used by Scrapling) from making network calls."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def request(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            "Network access is blocked during tests — this suite must run fully offline."
        )

    def get(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            "Network access is blocked during tests — this suite must run fully offline."
        )

    def post(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            "Network access is blocked during tests — this suite must run fully offline."
        )

    def put(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            "Network access is blocked during tests — this suite must run fully offline."
        )

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            "Network access is blocked during tests — this suite must run fully offline."
        )

    def head(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            "Network access is blocked during tests — this suite must run fully offline."
        )

    def options(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            "Network access is blocked during tests — this suite must run fully offline."
        )

    def patch(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            "Network access is blocked during tests — this suite must run fully offline."
        )

    def close(self) -> None:
        pass

    def __enter__(self) -> "_BlockedCurlSession":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


# Patch scrapling's CurlSession at module level BEFORE any test imports scrapling.
# This must happen before apps.scraping.fetching is imported (which imports scrapling).
_patch_scrapling = patch("scrapling.engines.static.CurlSession", _BlockedCurlSession)
_patch_scrapling.start()

# Also patch AsyncSession for dynamic/stealthy fetchers
_patch_async = patch("scrapling.engines.static.AsyncCurlSession", _BlockedCurlSession)
_patch_async.start()


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Raise on ANY outbound network call during tests."""

    class BlockedSocket(_ORIGINAL_SOCKET):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError(
                "Network access is blocked during tests — this suite must run fully offline."
            )

        def __enter__(self) -> Any:
            raise AssertionError("Network access is blocked during tests.")

        def __exit__(self, *args: Any) -> Any:
            raise AssertionError("Network access is blocked during tests.")

    monkeypatch.setattr(socket, "socket", BlockedSocket)
    yield


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Clean up patches at end of test session."""
    _patch_scrapling.stop()
    _patch_async.stop()
