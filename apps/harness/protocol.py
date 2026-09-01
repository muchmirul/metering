"""Typed immutable genome contract for evolutionary harness candidates.

Candidate text and Python bootstrap code are data at this boundary.  Validation
never imports or executes candidate-owned Python on the host.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from apps._support.wire import canonical_digest, canonical_json, decode_json_object
from apps.agent_protocol import ProtocolError, require_exact_keys, require_sha256

HARNESS_SCHEMA = "evolutionary-harness-v1"
HARNESS_SCHEMA_VERSION = 1
MANIFEST_NAME = "harness.json"
MAX_FILE_BYTES = 65_536
MAX_CANDIDATE_BYTES = 262_144
REQUIRED_LOCI = (
    "compaction_policy",
    "context_policy",
    "dependency_lock",
    "entrypoint",
    "ipython_bootstrap",
    "snapshot_policy",
    "subagent_policy",
    "system_prompt",
    "tool_policy",
)
POLICY_LOCI = {
    "compaction_policy",
    "context_policy",
    "entrypoint",
    "snapshot_policy",
    "subagent_policy",
    "tool_policy",
}


class HarnessProtocolError(ValueError):
    """Raised when a candidate does not implement evolutionary-harness-v1."""


@dataclass(frozen=True)
class HarnessCandidate:
    """One validated, immutable harness phenotype source tree."""

    root: Path
    manifest: dict[str, object]
    manifest_id: str
    paths: dict[str, str]
    texts: dict[str, str]
    policies: dict[str, dict[str, object]]
    dependencies: tuple[str, ...]

    def text(self, locus: str) -> str:
        return self.texts[locus]

    def policy(self, locus: str) -> dict[str, object]:
        return self.policies[locus]


class _ManifestStructure:
    def __init__(self, document: dict[str, object]) -> None:
        try:
            require_exact_keys(
                document,
                {"harness_schema", "loci", "schema_version"},
                "harness manifest",
            )
            if document["harness_schema"] != HARNESS_SCHEMA:
                raise ProtocolError(
                    f"harness manifest.harness_schema must be {HARNESS_SCHEMA}"
                )
            if (
                type(document["schema_version"]) is not int
                or document["schema_version"] != HARNESS_SCHEMA_VERSION
            ):
                raise ProtocolError("harness manifest.schema_version must be 1")
            raw_loci = document["loci"]
            if type(raw_loci) is not list or len(raw_loci) != len(REQUIRED_LOCI):
                raise ProtocolError(
                    f"harness manifest.loci must contain exactly {len(REQUIRED_LOCI)} loci"
                )
            entries: list[dict[str, str]] = []
            seen_names: set[str] = set()
            seen_paths: set[str] = set()
            for index, raw in enumerate(raw_loci):
                location = f"harness manifest.loci[{index}]"
                if type(raw) is not dict:
                    raise ProtocolError(f"{location} must be a JSON object")
                require_exact_keys(raw, {"name", "path", "sha256"}, location)
                name = raw["name"]
                if type(name) is not str or name not in REQUIRED_LOCI:
                    raise ProtocolError(f"{location}.name is not a supported locus")
                if name in seen_names:
                    raise ProtocolError(f"duplicate harness locus: {name}")
                path = _candidate_path(raw["path"], f"{location}.path")
                if path == MANIFEST_NAME or path in seen_paths:
                    raise ProtocolError(f"duplicate or reserved harness path: {path}")
                sha256 = require_sha256(raw["sha256"], f"{location}.sha256")
                seen_names.add(name)
                seen_paths.add(path)
                entries.append({"name": name, "path": path, "sha256": sha256})
            if seen_names != set(REQUIRED_LOCI):
                missing = ", ".join(sorted(set(REQUIRED_LOCI) - seen_names))
                raise ProtocolError(f"harness manifest is missing loci: {missing}")
            if [item["name"] for item in entries] != list(REQUIRED_LOCI):
                raise ProtocolError("harness manifest.loci must be sorted by name")
        except ProtocolError as exc:
            raise HarnessProtocolError(str(exc)) from exc
        self.entries = entries


def _candidate_path(value: object, location: str) -> str:
    if type(value) is not str or not value or "\x00" in value or "\\" in value:
        raise ProtocolError(f"{location} must be a normalized relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", "..", ".git"} for part in path.parts)
    ):
        raise ProtocolError(f"{location} must be a normalized relative POSIX path")
    return value


def _read_bytes(path: Path, location: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise HarnessProtocolError(f"{location} must be one regular file")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise HarnessProtocolError(f"cannot read {location}: {exc}") from exc
    if len(data) > MAX_FILE_BYTES:
        raise HarnessProtocolError(f"{location} exceeds {MAX_FILE_BYTES} bytes")
    return data


def _utf8(data: bytes, location: str, *, nonempty: bool = True) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HarnessProtocolError(f"{location} must be UTF-8") from exc
    if (nonempty and not text) or "\x00" in text:
        qualifier = "non-empty " if nonempty else ""
        raise HarnessProtocolError(f"{location} must be {qualifier}UTF-8 without NUL")
    return text


def _json_policy(text: str, locus: str) -> dict[str, object]:
    try:
        document = decode_json_object(text, HarnessProtocolError)
    except HarnessProtocolError:
        raise
    if text != canonical_json(document) + "\n":
        raise HarnessProtocolError(
            f"{locus} must be canonical JSON followed by newline"
        )
    return document


def _integer(
    value: object,
    location: str,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise HarnessProtocolError(
            f"{location} must be an integer from {minimum} through {maximum}"
        )
    return value


def _boolean(value: object, location: str) -> bool:
    if type(value) is not bool:
        raise HarnessProtocolError(f"{location} must be a boolean")
    return value


def _version(document: dict[str, object], locus: str, keys: set[str]) -> None:
    try:
        require_exact_keys(document, keys | {"schema_version"}, locus)
    except ProtocolError as exc:
        raise HarnessProtocolError(str(exc)) from exc
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise HarnessProtocolError(f"{locus}.schema_version must be 1")


def _validate_context(document: dict[str, object]) -> dict[str, object]:
    locus = "context_policy"
    _version(
        document,
        locus,
        {
            "include_code",
            "include_kernel_digest",
            "include_stderr",
            "max_event_characters",
            "max_task_characters",
            "max_transcript_characters",
        },
    )
    return {
        "include_code": _boolean(document["include_code"], f"{locus}.include_code"),
        "include_kernel_digest": _boolean(
            document["include_kernel_digest"], f"{locus}.include_kernel_digest"
        ),
        "include_stderr": _boolean(
            document["include_stderr"], f"{locus}.include_stderr"
        ),
        "max_event_characters": _integer(
            document["max_event_characters"],
            f"{locus}.max_event_characters",
            256,
            65_536,
        ),
        "max_task_characters": _integer(
            document["max_task_characters"],
            f"{locus}.max_task_characters",
            256,
            65_536,
        ),
        "max_transcript_characters": _integer(
            document["max_transcript_characters"],
            f"{locus}.max_transcript_characters",
            2_048,
            262_144,
        ),
        "schema_version": 1,
    }


def _validate_compaction(document: dict[str, object]) -> dict[str, object]:
    locus = "compaction_policy"
    _version(
        document,
        locus,
        {"keep_initial_event", "keep_recent_events", "mode", "trigger_characters"},
    )
    if document["mode"] != "hash-drop-v1":
        raise HarnessProtocolError(f"{locus}.mode must be hash-drop-v1")
    return {
        "keep_initial_event": _boolean(
            document["keep_initial_event"], f"{locus}.keep_initial_event"
        ),
        "keep_recent_events": _integer(
            document["keep_recent_events"],
            f"{locus}.keep_recent_events",
            1,
            64,
        ),
        "mode": "hash-drop-v1",
        "trigger_characters": _integer(
            document["trigger_characters"],
            f"{locus}.trigger_characters",
            1_024,
            262_144,
        ),
        "schema_version": 1,
    }


def _validate_tools(document: dict[str, object]) -> dict[str, object]:
    locus = "tool_policy"
    _version(
        document,
        locus,
        {
            "execute_timeout_ms",
            "interrupt_grace_ms",
            "max_code_characters",
            "max_executions",
            "max_output_characters",
        },
    )
    return {
        "execute_timeout_ms": _integer(
            document["execute_timeout_ms"], f"{locus}.execute_timeout_ms", 10, 60_000
        ),
        "interrupt_grace_ms": _integer(
            document["interrupt_grace_ms"], f"{locus}.interrupt_grace_ms", 10, 5_000
        ),
        "max_code_characters": _integer(
            document["max_code_characters"],
            f"{locus}.max_code_characters",
            64,
            65_536,
        ),
        "max_executions": _integer(
            document["max_executions"], f"{locus}.max_executions", 1, 64
        ),
        "max_output_characters": _integer(
            document["max_output_characters"],
            f"{locus}.max_output_characters",
            128,
            65_536,
        ),
        "schema_version": 1,
    }


def _validate_subagents(document: dict[str, object]) -> dict[str, object]:
    locus = "subagent_policy"
    _version(
        document,
        locus,
        {"enabled", "max_calls", "max_depth", "max_task_characters", "max_turns"},
    )
    enabled = _boolean(document["enabled"], f"{locus}.enabled")
    normalized = {
        "enabled": enabled,
        "max_calls": _integer(document["max_calls"], f"{locus}.max_calls", 0, 16),
        "max_depth": _integer(document["max_depth"], f"{locus}.max_depth", 0, 4),
        "max_task_characters": _integer(
            document["max_task_characters"],
            f"{locus}.max_task_characters",
            64,
            16_384,
        ),
        "max_turns": _integer(document["max_turns"], f"{locus}.max_turns", 1, 32),
        "schema_version": 1,
    }
    if not enabled and (normalized["max_calls"] != 0 or normalized["max_depth"] != 0):
        raise HarnessProtocolError(
            f"{locus} disabled policy must have zero max_calls and max_depth"
        )
    if enabled and (normalized["max_calls"] == 0 or normalized["max_depth"] == 0):
        raise HarnessProtocolError(
            f"{locus} enabled policy must have positive max_calls and max_depth"
        )
    return normalized


def _validate_snapshot(document: dict[str, object]) -> dict[str, object]:
    locus = "snapshot_policy"
    _version(
        document,
        locus,
        {"allowed_names", "max_bytes", "mode", "restore_after_restart"},
    )
    if document["mode"] not in {"disabled-v1", "after-each-success-v1"}:
        raise HarnessProtocolError(
            f"{locus}.mode must be disabled-v1 or after-each-success-v1"
        )
    raw_names = document["allowed_names"]
    if type(raw_names) is not list or len(raw_names) > 64:
        raise HarnessProtocolError(
            f"{locus}.allowed_names must be an array of at most 64 names"
        )
    names: list[str] = []
    for index, name in enumerate(raw_names):
        if (
            type(name) is not str
            or not name.isidentifier()
            or name.startswith("_")
            or name in names
        ):
            raise HarnessProtocolError(
                f"{locus}.allowed_names[{index}] must be a unique public Python identifier"
            )
        names.append(name)
    if names != sorted(names):
        raise HarnessProtocolError(f"{locus}.allowed_names must be sorted")
    mode = cast(str, document["mode"])
    if mode == "disabled-v1" and names:
        raise HarnessProtocolError(
            f"{locus} disabled policy must have no allowed names"
        )
    return {
        "allowed_names": names,
        "max_bytes": _integer(
            document["max_bytes"], f"{locus}.max_bytes", 64, 1_048_576
        ),
        "mode": mode,
        "restore_after_restart": _boolean(
            document["restore_after_restart"], f"{locus}.restore_after_restart"
        ),
        "schema_version": 1,
    }


def _validate_entrypoint(document: dict[str, object]) -> dict[str, object]:
    locus = "entrypoint"
    _version(document, locus, {"max_invalid_actions", "max_turns", "protocol"})
    if document["protocol"] != "recursive-ipython-actions-v1":
        raise HarnessProtocolError(
            f"{locus}.protocol must be recursive-ipython-actions-v1"
        )
    return {
        "max_invalid_actions": _integer(
            document["max_invalid_actions"], f"{locus}.max_invalid_actions", 0, 8
        ),
        "max_turns": _integer(document["max_turns"], f"{locus}.max_turns", 1, 64),
        "protocol": "recursive-ipython-actions-v1",
        "schema_version": 1,
    }


_POLICY_VALIDATORS = {
    "compaction_policy": _validate_compaction,
    "context_policy": _validate_context,
    "entrypoint": _validate_entrypoint,
    "snapshot_policy": _validate_snapshot,
    "subagent_policy": _validate_subagents,
    "tool_policy": _validate_tools,
}


def _dependencies(text: str) -> tuple[str, ...]:
    lines = text.splitlines()
    if not lines or lines[0] != "# evolutionary-harness-dependencies-v1":
        raise HarnessProtocolError(
            "dependency_lock must start with # evolutionary-harness-dependencies-v1"
        )
    requirements: list[str] = []
    for index, line in enumerate(lines[1:], start=2):
        if not line or line.startswith("#"):
            raise HarnessProtocolError(
                f"dependency_lock line {index} must be one exact pinned requirement"
            )
        if line.count("==") != 1:
            raise HarnessProtocolError(
                f"dependency_lock line {index} must use one exact == pin"
            )
        name, version = line.split("==", 1)
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        if (
            not name
            or not version
            or any(character not in allowed for character in name + version)
        ):
            raise HarnessProtocolError(
                f"dependency_lock line {index} contains unsupported characters"
            )
        normalized = f"{name.lower().replace('_', '-')}=={version}"
        if line != normalized:
            raise HarnessProtocolError(
                f"dependency_lock line {index} must use normalized package spelling"
            )
        requirements.append(line)
    if not requirements or requirements != sorted(requirements):
        raise HarnessProtocolError(
            "dependency_lock requirements must be non-empty, unique, and sorted"
        )
    if len(set(requirements)) != len(requirements):
        raise HarnessProtocolError("dependency_lock contains duplicate requirements")
    if text != "\n".join(lines) + "\n":
        raise HarnessProtocolError("dependency_lock must end with exactly one newline")
    return tuple(requirements)


def _workspace_files(root: Path) -> set[str]:
    files: set[str] = set()
    try:
        entries = list(root.rglob("*"))
    except OSError as exc:
        raise HarnessProtocolError(f"cannot inspect candidate checkout: {exc}") from exc
    for path in entries:
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".git":
            continue
        name = relative.as_posix()
        if path.is_symlink():
            raise HarnessProtocolError(f"candidate path may not be a symlink: {name}")
        if path.is_file():
            files.add(name)
        elif not path.is_dir():
            raise HarnessProtocolError(f"candidate path is not regular: {name}")
    return files


def load_candidate(root: Path, *, entrypoint: str = MANIFEST_NAME) -> HarnessCandidate:
    """Validate and load one materialized candidate checkout."""

    root = root.absolute()
    if root.is_symlink() or not root.is_dir():
        raise HarnessProtocolError(
            "candidate checkout must be one non-symlink directory"
        )
    if entrypoint != MANIFEST_NAME:
        raise HarnessProtocolError(f"Git artifact entrypoint must be {MANIFEST_NAME}")
    manifest_data = _read_bytes(root / MANIFEST_NAME, "harness manifest")
    manifest_text = _utf8(manifest_data, "harness manifest")
    manifest = decode_json_object(manifest_text, HarnessProtocolError)
    if manifest_text != canonical_json(manifest) + "\n":
        raise HarnessProtocolError(
            "harness manifest must be canonical JSON followed by newline"
        )
    structure = _ManifestStructure(manifest)
    expected_paths = {MANIFEST_NAME, *(entry["path"] for entry in structure.entries)}
    actual_paths = _workspace_files(root)
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        extra = sorted(actual_paths - expected_paths)
        details: list[str] = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if extra:
            details.append(f"undeclared: {', '.join(extra)}")
        raise HarnessProtocolError(
            f"candidate files do not match typed loci ({'; '.join(details)})"
        )

    texts: dict[str, str] = {}
    paths: dict[str, str] = {}
    total = len(manifest_data)
    for entry in structure.entries:
        name = entry["name"]
        relative = entry["path"]
        data = _read_bytes(root / relative, f"harness locus {name}")
        total += len(data)
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise HarnessProtocolError(f"harness locus digest does not match: {name}")
        texts[name] = _utf8(data, f"harness locus {name}")
        paths[name] = relative
    if total > MAX_CANDIDATE_BYTES:
        raise HarnessProtocolError(f"candidate exceeds {MAX_CANDIDATE_BYTES} bytes")

    policies: dict[str, dict[str, object]] = {}
    for locus in POLICY_LOCI:
        policies[locus] = _POLICY_VALIDATORS[locus](_json_policy(texts[locus], locus))
    dependencies = _dependencies(texts["dependency_lock"])
    try:
        compile(texts["ipython_bootstrap"], paths["ipython_bootstrap"], "exec")
    except (SyntaxError, ValueError) as exc:
        raise HarnessProtocolError(
            f"ipython_bootstrap is not valid Python: {exc}"
        ) from exc
    if not texts["system_prompt"].strip():
        raise HarnessProtocolError(
            "system_prompt must contain non-whitespace instructions"
        )

    normalized_manifest = {
        "harness_schema": HARNESS_SCHEMA,
        "loci": structure.entries,
        "schema_version": HARNESS_SCHEMA_VERSION,
    }
    if manifest != normalized_manifest:
        raise HarnessProtocolError("harness manifest is not normalized")
    return HarnessCandidate(
        root=root,
        manifest=normalized_manifest,
        manifest_id=canonical_digest(
            {"manifest": normalized_manifest, "manifest_identity": HARNESS_SCHEMA}
        ),
        paths=paths,
        texts=texts,
        policies=policies,
        dependencies=dependencies,
    )


def refresh_manifest(root: Path) -> HarnessCandidate:
    """Refresh declared locus digests after a fixed mutator edits locus files."""

    root = root.absolute()
    manifest_path = root / MANIFEST_NAME
    source = _utf8(_read_bytes(manifest_path, "harness manifest"), "harness manifest")
    document = decode_json_object(source, HarnessProtocolError)
    structure = _ManifestStructure(document)
    entries: list[dict[str, str]] = []
    for entry in structure.entries:
        data = _read_bytes(root / entry["path"], f"harness locus {entry['name']}")
        entries.append(
            {
                "name": entry["name"],
                "path": entry["path"],
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    normalized = {
        "harness_schema": HARNESS_SCHEMA,
        "loci": entries,
        "schema_version": HARNESS_SCHEMA_VERSION,
    }
    try:
        manifest_path.write_text(
            canonical_json(normalized) + "\n", encoding="utf-8", newline=""
        )
    except OSError as exc:
        raise HarnessProtocolError(f"cannot refresh harness manifest: {exc}") from exc
    return load_candidate(root)
