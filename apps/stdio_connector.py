"""Compatibility facade for source-only canonical JSON transport.

New application modules import the focused modules under :mod:`apps._support`.
This facade preserves the established source import path for external examples.
"""

from __future__ import annotations

try:  # Package imports used by refactored modules.
    from apps._support.process import (
        JsonProcessError,
        kill_process_tree,
        run_json_process,
    )
    from apps._support.stdio import run_stdio_application
    from apps._support.wire import (
        JsonDocument,
        canonical_digest,
        canonical_json,
        decode_json_object,
        error_document,
        strict_json_float,
        write_document,
    )
except ModuleNotFoundError:  # Legacy scripts that put ``apps/`` on sys.path.
    from _support.process import JsonProcessError, kill_process_tree, run_json_process
    from _support.stdio import run_stdio_application
    from _support.wire import (
        JsonDocument,
        canonical_digest,
        canonical_json,
        decode_json_object,
        error_document,
        strict_json_float,
        write_document,
    )

__all__ = [
    "JsonDocument",
    "JsonProcessError",
    "canonical_digest",
    "canonical_json",
    "decode_json_object",
    "error_document",
    "kill_process_tree",
    "run_json_process",
    "run_stdio_application",
    "strict_json_float",
    "write_document",
]
