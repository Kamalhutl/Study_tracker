"""Root conftest — project-wide test guarantees.

Prompt 2 ground rule 1: this suite must run fully offline. The socket guard
below is autouse for EVERY test under the project root; there is deliberately
no opt-out marker. Tests that need network fixtures must mock the fetch layer.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

_ORIGINAL_SOCKET = socket.socket


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
