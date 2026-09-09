"""Pure, additive reviewed task context; references are data, never authority."""

from __future__ import annotations

import hashlib
from typing import cast

from apps.harness.workspace import normalized_path

CONTEXT_SCHEMA = "agentvolve-task-context-v1"
MAX_SOURCE_BYTES = 65_536
MAX_CONTEXT_BYTES = 131_072
MAX_SOURCES = 16


def normalize_task_context(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != {
        "context_schema", "requirements", "assumptions", "read_only_paths", "sources",
    } or value["context_schema"] != CONTEXT_SCHEMA:
        raise ValueError("task context has an unsupported schema or fields")
    for key in ("requirements", "assumptions"):
        items = value[key]
        if type(items) is not list or len(items) > 32 or any(
            type(item) is not str or not item.strip() or len(item) > 1000 or "\0" in item
            for item in items
        ):
            raise ValueError(f"task context.{key} must contain at most 32 bounded statements")
    paths = value["read_only_paths"]
    if type(paths) is not list or len(paths) > 64:
        raise ValueError("task context.read_only_paths must contain at most 64 paths")
    normalized = [normalized_path(path, "task context.read_only_paths") for path in paths]
    if normalized != sorted(set(normalized)):
        raise ValueError("task context.read_only_paths must be sorted and unique")
    sources = value["sources"]
    if type(sources) is not list or len(sources) > MAX_SOURCES:
        raise ValueError(f"task context.sources must contain at most {MAX_SOURCES} snapshots")
    total = 0
    uris = []
    for source in sources:
        if type(source) is not dict or set(source) != {"uri", "representation", "sha256", "content"}:
            raise ValueError("task source has the wrong fields")
        uri, content = source["uri"], source["content"]
        if type(uri) is not str or not uri or len(uri) > 4096 or any(ord(c) < 32 for c in uri):
            raise ValueError("task source URI must be bounded text without controls")
        if source["representation"] not in ("utf-8", "html-text"):
            raise ValueError("task source representation is unsupported")
        if type(content) is not str or "\0" in content:
            raise ValueError("task source content must be UTF-8 text without NUL")
        try:
            payload = content.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("task source content must be UTF-8") from exc
        if len(payload) > MAX_SOURCE_BYTES:
            raise ValueError(f"task source exceeds {MAX_SOURCE_BYTES} bytes; narrow the input")
        if source["sha256"] != hashlib.sha256(payload).hexdigest():
            raise ValueError("task source snapshot digest does not match its content")
        total += len(payload)
        uris.append(uri)
    if total > MAX_CONTEXT_BYTES:
        raise ValueError(f"task source context exceeds {MAX_CONTEXT_BYTES} bytes; narrow the task")
    if uris != sorted(set(uris)):
        raise ValueError("task source snapshots must be URI-sorted and unique")
    return cast(dict[str, object], value)


def require_read_only_paths(context: dict[str, object], allowed: list[str]) -> None:
    for path in cast(list[str], context["read_only_paths"]):
        if any(path == writable or path.startswith(writable + "/") or writable.startswith(path + "/") for writable in allowed):
            raise ValueError(f"read-only task input overlaps a writable path: {path}")
