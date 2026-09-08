"""Read-only inventories, exact blobs, and diffs for registered candidate snapshots."""

from __future__ import annotations

import base64
import hashlib
import re

from apps.coding_agent.candidate_view import ExperimentView, _safe_path
from apps.coding_agent.git_inventory import inventory
from apps.coding_agent.inspection_git import git_bytes, object_digest
from apps.coding_agent.operator_view import OperatorViewError, _page

OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
MAX_FILES = 2000
MAX_BLOB = 1024 * 1024
MAX_TREE_OUTPUT = 4 * 1024 * 1024
MAX_DIFF = 4 * 1024 * 1024
FILE_PAGE = 100
TEXT_PAGE = 200


def path_key(path: bytes) -> str:
    return base64.urlsafe_b64encode(path).decode("ascii").rstrip("=")


def display_path(path: bytes) -> str:
    # Identity is path_id, not this sanitized presentation string.
    return "".join(
        character if character.isprintable() else "?"
        for character in path.decode("utf-8", "backslashreplace")
    )


class CandidateFiles:
    """A bounded inventory cache belonging to one frozen trace-view snapshot."""

    def __init__(self, view: ExperimentView):
        self.view = view
        self.repository = _safe_path(view.root, "candidate.git")
        self.inventories: dict[str, dict[str, dict]] = {}
        self.inventory_bytes = 0

    def commit(self, identity: str) -> str:
        if identity not in self.view.candidates:
            raise OperatorViewError("unknown registered candidate")
        node = self.view.node(identity)
        commit, tree = node["commit"], node["git_tree"]
        if not all(
            type(value) is str and OID.fullmatch(value) for value in (commit, tree)
        ):
            raise OperatorViewError("candidate has no valid immutable Git binding")
        return commit

    def inventory(self, identity: str) -> dict[str, dict]:
        if identity in self.inventories:
            return self.inventories[identity]
        commit = self.commit(identity)
        parent = self.view.node(identity)["parent_candidate_id"]
        rows, tree_bytes = inventory(
            self.repository,
            commit,
            self.view.node(identity)["git_tree"],
            max_files=MAX_FILES,
            parent=self.commit(parent) if parent is not None else None,
        )
        entries = {
            path_key(path): {
                "path_id": path_key(path),
                "path": display_path(path),
                "blob": oid,
                "mode": mode,
                "object_type": "commit" if mode == "160000" else "blob",
                "size": size,
            }
            for path, mode, oid, size in rows
        }
        if self.inventory_bytes + tree_bytes > 16 * 1024 * 1024:
            self.inventories.clear()
            self.inventory_bytes = 0
        self.inventories[identity] = entries
        self.inventory_bytes += tree_bytes
        return entries

    def entry(self, identity: str, key: str) -> dict:
        entry = self.inventory(identity).get(key)
        if entry is None:
            raise OperatorViewError("file is absent from the bound candidate snapshot")
        return entry

    def changes(self, identity: str, base: str | None = None) -> list[dict]:
        current = self.inventory(identity)
        parent = (
            base
            if base is not None
            else self.view.node(identity)["parent_candidate_id"]
        )
        previous = self.inventory(parent) if parent is not None else {}
        # Explicit A/M/D semantics; optional Git rename inference is added below, never identity.
        rows = []
        for key in current.keys() | previous.keys():
            old, new = previous.get(key), current.get(key)
            status = (
                "added"
                if old is None
                else "deleted"
                if new is None
                else "unchanged"
                if (old["blob"], old["mode"]) == (new["blob"], new["mode"])
                else "modified"
            )
            rows.append({**(new or old), "change": status, "before": old, "after": new})
        return sorted(
            rows,
            key=lambda row: base64.urlsafe_b64decode(
                row["path_id"] + "=" * (-len(row["path_id"]) % 4)
            ),
        )

    def change(self, identity: str, key: str, base: str | None = None) -> dict:
        row = next(
            (row for row in self.changes(identity, base) if row["path_id"] == key), None
        )
        if row is None:
            raise OperatorViewError("file is absent from both compared snapshots")
        return {
            "file": row,
            "base_candidate_id": base
            or self.view.node(identity)["parent_candidate_id"],
        }

    def files(
        self,
        identity: str,
        offset: int = 0,
        *,
        changed: bool = False,
        base: str | None = None,
    ) -> dict:
        rows = self.changes(identity, base)
        if changed:
            rows = [row for row in rows if row["change"] != "unchanged"]
        return {
            "candidate_id": identity,
            "commit": self.commit(identity),
            "base_candidate_id": base
            or self.view.node(identity)["parent_candidate_id"],
            "items": rows[offset : offset + FILE_PAGE],
            "total_items": len(rows),
            **_page(offset, len(rows), FILE_PAGE),
            "semantics": "Exact-path snapshot comparison. Deleted entries belong to the base, not the child.",
        }

    def blob(self, identity: str, key: str) -> bytes:
        entry = self.entry(identity, key)
        if entry["object_type"] != "blob":
            raise OperatorViewError(
                "submodule references are metadata only; no external repository is opened"
            )
        if entry["size"] is None or not 0 <= entry["size"] <= MAX_BLOB:
            raise OperatorViewError(
                "file exceeds the 1 MiB inspection/download bound; use its immutable Git object"
            )
        data = git_bytes(
            self.repository, ["cat-file", "blob", entry["blob"]], limit=MAX_BLOB
        )
        if (
            len(data) != entry["size"]
            or object_digest("blob", data, entry["blob"]) != entry["blob"]
        ):
            raise OperatorViewError(
                "Git blob bytes do not match the recorded object identity"
            )
        return data

    def content(self, identity: str, key: str, offset: int = 0) -> dict:
        entry = self.entry(identity, key)
        result = {
            "candidate_id": identity,
            "commit": self.commit(identity),
            "file": entry,
            "text": None,
            "warning": None,
            "total_items": 0,
            **_page(offset, 0, TEXT_PAGE),
        }
        try:
            data = self.blob(identity, key)
        except OperatorViewError as exc:
            return {**result, "warning": str(exc)}
        try:
            if b"\0" in data:
                raise UnicodeError()
            text = data.decode("utf-8")
        except UnicodeError:
            return {
                **result,
                "warning": "Binary or non-UTF-8 file; exact bytes can be downloaded within the size bound.",
            }
        # Keep CRLF and the final-newline state; do not normalize source bytes.
        fragments = [text[index : index + 1000] for index in range(0, len(text), 1000)]
        return {
            **result,
            "text": "".join(fragments[offset : offset + TEXT_PAGE]),
            "sha256": hashlib.sha256(data).hexdigest(),
            "total_items": len(fragments),
            **_page(offset, len(fragments), TEXT_PAGE),
            "warning": "Symlink target text only; the link is never followed."
            if entry["mode"] == "120000"
            else None,
            "has_final_newline": data.endswith(b"\n"),
            "crlf_count": data.count(b"\r\n"),
            "semantics": "UTF-8 source fragments (1000 characters each); exact raw bytes are a separate download.",
        }

    def diff(self, identity: str, key: str, base: str | None, offset: int = 0) -> dict:
        parent = (
            base
            if base is not None
            else self.view.node(identity)["parent_candidate_id"]
        )
        if parent is None:
            raise OperatorViewError("seed has no parent; choose a comparison candidate")
        row = self.change(identity, key, parent)["file"]
        # Select paths only after membership lookup; --literal-pathspecs defeats :(...) magic.
        path = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
        raw = git_bytes(
            self.repository,
            [
                "--literal-pathspecs",
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--submodule=short",
                "--ignore-submodules=none",
                "--binary",
                "--no-renames",
                self.commit(parent),
                self.commit(identity),
                "--",
                path,
            ],
            limit=MAX_DIFF,
        )
        text = raw.decode("utf-8", "backslashreplace")
        fragments = [text[index : index + 1000] for index in range(0, len(text), 1000)]
        return {
            "candidate_id": identity,
            "base_candidate_id": parent,
            "file": row,
            "text": "".join(fragments[offset : offset + TEXT_PAGE]),
            "total_items": len(fragments),
            **_page(offset, len(fragments), TEXT_PAGE),
            "semantics": "Git binary-capable exact-path diff; non-UTF-8 bytes are escaped for display. This is not a byte-exact patch download.",
        }

    def renames(self, identity: str, base: str | None = None) -> list[dict]:
        parent = (
            base
            if base is not None
            else self.view.node(identity)["parent_candidate_id"]
        )
        if parent is None:
            return []
        self.inventory(parent)
        self.inventory(identity)
        raw = git_bytes(
            self.repository,
            [
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--submodule=short",
                "--ignore-submodules=none",
                "--name-status",
                "-z",
                "--find-renames=50%",
                "-l2000",
                self.commit(parent),
                self.commit(identity),
                "--",
            ],
            limit=MAX_TREE_OUTPUT,
        )
        fields = iter(raw.rstrip(b"\0").split(b"\0")) if raw else iter([])
        rows = []
        try:
            for status in fields:
                old = next(fields)
                if status.startswith(b"R"):
                    new = next(fields)
                    rows.append(
                        {
                            "before": self.entry(parent, path_key(old)),
                            "after": self.entry(identity, path_key(new)),
                            "similarity_percent": int(status[1:]),
                            "authority": "inferred-only",
                        }
                    )
        except (StopIteration, ValueError) as exc:
            raise OperatorViewError("malformed Git rename inference") from exc
        return rows
