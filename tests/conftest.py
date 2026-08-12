from __future__ import annotations

import socket

import pytest

from contract import MeteringAPI


@pytest.fixture(scope="session")
def api() -> MeteringAPI:
    return MeteringAPI()


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Metering is required to run without a model server or network access."""

    def blocked(*args, **kwargs):
        raise AssertionError("the deterministic Metering suite attempted network access")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
