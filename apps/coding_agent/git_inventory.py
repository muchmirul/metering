"""Verify Git tree bytes before mapping raw paths to blobs; never traverse host files."""

from __future__ import annotations

import time
from pathlib import Path

from apps.coding_agent.inspection_git import git_bytes, object_digest
from apps.coding_agent.operator_view import OperatorViewError

MAX_TREE_BYTES = 8 * 1024 * 1024


def inventory(
    repository: Path,
    commit: str,
    tree: str,
    *,
    max_files: int,
    parent: str | None = None,
) -> tuple[list[tuple[bytes, str, str, int | None]], int]:
    deadline = time.monotonic() + 20

    def read(arguments: list[str], *, limit: int, source: bytes | None = None) -> bytes:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise OperatorViewError("Git inventory exceeded its time bound")
        return git_bytes(
            repository,
            arguments,
            limit=limit,
            timeout=min(5, remaining),
            input_bytes=source,
        )

    document = read(["cat-file", "commit", commit], limit=128 * 1024)
    if (
        object_digest("commit", document, commit) != commit
        or document.split(b"\n", 1)[0] != b"tree " + tree.encode()
    ):
        raise OperatorViewError(
            "candidate commit bytes do not bind the recorded Git tree"
        )
    header = document.split(b"\n\n", 1)[0].splitlines()
    actual_parents = [
        line.removeprefix(b"parent ").decode("ascii")
        for line in header
        if line.startswith(b"parent ")
    ]
    if parent is not None and actual_parents != [parent]:
        raise OperatorViewError("Git parent disagrees with recorded candidate ancestry")
    pending = [(tree, b"")]
    cache: dict[str, bytes] = {}
    output: dict[bytes, tuple[str, str]] = {}
    total = 0
    depth = 0
    while pending:
        depth += 1
        if depth > 64 or len(pending) + len(cache) > 4096:
            raise OperatorViewError("Git inventory exceeds its directory/depth bound")
        missing = sorted({oid for oid, _prefix in pending} - cache.keys())
        if missing:
            batch = read(
                ["cat-file", "--batch"],
                limit=MAX_TREE_BYTES + 512 * 1024,
                source="".join(oid + "\n" for oid in missing).encode(),
            )
            position = 0
            try:
                for oid in missing:
                    end = batch.index(b"\n", position)
                    raw_oid, kind, raw_size = batch[position:end].split()
                    size = int(raw_size)
                    if (
                        raw_oid.decode() != oid
                        or kind != b"tree"
                        or not 0 <= size <= MAX_TREE_BYTES
                    ):
                        raise ValueError("unexpected object")
                    body = batch[end + 1 : end + 1 + size]
                    position = end + 1 + size
                    if (
                        batch[position : position + 1] != b"\n"
                        or object_digest("tree", body, oid) != oid
                    ):
                        raise ValueError("tree digest mismatch")
                    position += 1
                    total += len(body)
                    if total > MAX_TREE_BYTES:
                        raise ValueError("tree byte bound")
                    cache[oid] = body
                if position != len(batch):
                    raise ValueError("unexpected trailing object data")
            except (ValueError, UnicodeError) as exc:
                raise OperatorViewError(
                    "Git tree bytes are missing, oversized, or do not match their identity"
                ) from exc
        following = []
        for oid, prefix in pending:
            body = cache[oid]
            position = 0
            names: set[bytes] = set()
            while position < len(body):
                try:
                    space = body.index(b" ", position)
                    end = body.index(b"\0", space + 1)
                    mode, name = body[position:space], body[space + 1 : end]
                    size = len(tree) // 2
                    child = body[end + 1 : end + 1 + size]
                    if (
                        len(child) != size
                        or not name
                        or name in {b".", b"..", b".git"}
                        or b"/" in name
                        or name in names
                    ):
                        raise ValueError("invalid tree entry")
                    names.add(name)
                    position = end + 1 + size
                    path, identity = prefix + name, child.hex()
                    if len(path) > 4096:
                        raise ValueError("path exceeds inspection bound")
                    if mode == b"40000":
                        following.append((identity, path + b"/"))
                    elif mode in {b"100644", b"100755", b"120000", b"160000"}:
                        if path in output:
                            raise ValueError("duplicate file path")
                        output[path] = (mode.decode(), identity)
                    else:
                        raise ValueError("unsupported mode")
                except ValueError as exc:
                    raise OperatorViewError("invalid Git tree inventory entry") from exc
                if len(output) > max_files:
                    raise OperatorViewError(
                        f"candidate file inventory exceeds {max_files} files"
                    )
        pending = following
    blob_ids = sorted({oid for mode, oid in output.values() if mode != "160000"})
    sizes = {}
    if blob_ids:
        information = read(
            ["cat-file", "--batch-check"],
            limit=512 * 1024,
            source="".join(oid + "\n" for oid in blob_ids).encode(),
        )
        try:
            rows = information.splitlines()
            if len(rows) != len(blob_ids):
                raise ValueError("missing object info")
            for expected, row in zip(blob_ids, rows, strict=True):
                oid, kind, raw_size = row.decode("ascii").split()
                if oid != expected or kind != "blob" or int(raw_size) < 0:
                    raise ValueError("invalid blob info")
                sizes[oid] = int(raw_size)
        except (ValueError, UnicodeError) as exc:
            raise OperatorViewError(
                "candidate file objects are absent or malformed"
            ) from exc
    return [
        (path, mode, oid, None if mode == "160000" else sizes[oid])
        for path, (mode, oid) in sorted(output.items())
    ], total
