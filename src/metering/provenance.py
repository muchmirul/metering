"""Pinned implementation provenance recorded in every v0 manifest."""

from __future__ import annotations

from typing import Final

PACKAGE_NAME: Final = "metering"
PACKAGE_VERSION: Final = "0.1.0"
CONTROLLER_VERSION: Final = "1"
VERIFIER_VERSION: Final = "1"
METER_VERSION: Final = "1"


def implementation_provenance() -> dict[str, str]:
    """Return the exact implementation declaration for a v0 run."""

    return {
        "package": PACKAGE_NAME,
        "package_version": PACKAGE_VERSION,
        "controller_version": CONTROLLER_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "meter_version": METER_VERSION,
    }
