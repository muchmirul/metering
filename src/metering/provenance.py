"""Pinned implementation provenance recorded in every Metering manifest."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Final

PACKAGE_NAME: Final = "metering"


def _package_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:  # Direct source import outside an installed project.
        return "0+uninstalled"


PACKAGE_VERSION: Final = _package_version()
CONTROLLER_VERSION: Final = "1"
VERIFIER_VERSION: Final = "1"
METER_VERSION: Final = "1"


def implementation_provenance() -> dict[str, str]:
    """Return the exact implementation declaration for a Metering run."""

    return {
        "package": PACKAGE_NAME,
        "package_version": PACKAGE_VERSION,
        "controller_version": CONTROLLER_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "meter_version": METER_VERSION,
    }
