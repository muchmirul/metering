from __future__ import annotations

import socket

import pytest

from v0_contract import V0API


@pytest.fixture(scope="session")
def api() -> V0API:
    return V0API()


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0 is required to run without a model server or network access."""

    def blocked(*args, **kwargs):
        raise AssertionError("the deterministic v0 suite attempted network access")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
