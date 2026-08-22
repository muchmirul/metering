"""Small, pure tools for measuring information."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .information import (
    ProbabilityError,
    entropy,
    kl_divergence,
    mutual_information,
    self_information,
)

try:
    __version__ = version("metering")
except PackageNotFoundError:  # Direct source import without installation.
    __version__ = "0+uninstalled"

__all__ = [
    "ProbabilityError",
    "entropy",
    "kl_divergence",
    "mutual_information",
    "self_information",
]
