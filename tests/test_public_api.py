from __future__ import annotations

import builtins
import importlib.util
import inspect
import socket
import tomllib
from pathlib import Path

import metering


ROOT = Path(__file__).resolve().parents[1]


def test_public_exports_are_exactly_the_measurement_surface():
    assert metering.__all__ == [
        "ProbabilityError",
        "entropy",
        "kl_divergence",
        "mutual_information",
        "self_information",
    ]


def test_public_signatures_stay_small_and_explicit():
    assert str(inspect.signature(metering.self_information)) == (
        "(probability: 'Real', *, base: 'Real' = 2) -> 'float'"
    )
    assert str(inspect.signature(metering.entropy)) == (
        "(probabilities: 'Iterable[Real]', *, base: 'Real' = 2) -> 'float'"
    )
    assert str(inspect.signature(metering.kl_divergence)) == (
        "(p: 'Iterable[Real]', q: 'Iterable[Real]', *, base: 'Real' = 2) -> 'float'"
    )
    assert str(inspect.signature(metering.mutual_information)) == (
        "(joint: 'Iterable[Iterable[Real]]', *, base: 'Real' = 2) -> 'float'"
    )


def test_legacy_product_modules_are_gone():
    legacy_modules = (
        "binding",
        "calibration",
        "events",
        "hidden_fault",
        "policies",
        "provenance",
        "replay",
        "report",
        "runner",
        "schema",
        "trace",
    )

    assert all(
        importlib.util.find_spec(f"metering.{module}") is None
        for module in legacy_modules
    )


def test_shipped_source_has_only_the_core_and_json_adapter():
    files = {
        path.name
        for path in (ROOT / "src" / "metering").iterdir()
        if path.is_file() and path.suffix == ".py"
    }

    assert files == {"__init__.py", "__main__.py", "information.py"}


def test_package_has_no_runtime_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert project["project"]["dependencies"] == []


def test_measurement_functions_do_not_open_files_or_sockets(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("measurement attempted external I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)

    assert metering.self_information(0.5) == 1.0
    assert metering.entropy([0.5, 0.5]) == 1.0
    assert metering.kl_divergence([0.5, 0.5], [0.5, 0.5]) == 0.0
    assert metering.mutual_information([[0.25, 0.25], [0.25, 0.25]]) == 0.0
