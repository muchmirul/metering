"""Git-backed history for explicit Metering request/response pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from . import __version__


SCHEMA_VERSION = 2
_HISTORY_BRANCH = "refs/heads/metering-history"
_PAIR_DIRECTORY = "measurement/pair"
_CONFIGURATION_PATH = f"{_PAIR_DIRECTORY}/configuration.json"
_RESULT_PATH = f"{_PAIR_DIRECTORY}/result.json"
_PROVENANCE_PATH = "measurement/provenance.json"
_EXPECTED_PATHS = (_CONFIGURATION_PATH, _PROVENANCE_PATH, _RESULT_PATH)
_PROVENANCE_KEYS = frozenset(
    {
        "implementation_sha256",
        "metering_version",
        "python_version",
        "schema_version",
        "source_commit",
        "source_dirty",
    }
)
_RESPONSE_KEYS = frozenset({"base", "infinite", "measure", "value"})
_GIT_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})").fullmatch
_SHA256 = re.compile(r"[0-9a-f]{64}").fullmatch
_GIT_TIMEOUT_SECONDS = 30


class CommandError(ValueError):
    """Raised when command-line arguments are malformed."""


class HistoryError(RuntimeError):
    """Raised when a measurement history is malformed or unavailable."""


class MeasurementRejected(RuntimeError):
    """Carries a normal rejection from the public Metering command."""

    def __init__(self, stderr: str) -> None:
        super().__init__(stderr)
        self.stderr = stderr


class _StrictArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CommandError(f"invalid command line: {message}")


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _parser() -> argparse.ArgumentParser:
    parser = _StrictArgumentParser(
        prog="metering-history",
        description=(
            "Record and inspect a Git history of Metering configurations "
            "and results."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser(
        "record",
        help="measure one JSON request and commit its configuration and result",
        allow_abbrev=False,
    )
    record.add_argument("history", type=Path, help="dedicated Git history directory")

    log = subparsers.add_parser(
        "log",
        help="print the current Git measurement history newest first",
        allow_abbrev=False,
    )
    log.add_argument("history", type=Path, help="dedicated Git history directory")

    verify = subparsers.add_parser(
        "verify",
        help="verify Git integrity, schemas, cleanliness, and measurement replay",
        allow_abbrev=False,
    )
    verify.add_argument("history", type=Path, help="dedicated Git history directory")
    return parser


def _write_json(stream: Any, value: dict[str, Any]) -> None:
    stream.write(canonical_json(value) + "\n")


def _write_error(code: str, message: str) -> None:
    _write_json(sys.stderr, {"error": {"code": code, "message": message}})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HistoryError(f"duplicate stored JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    raise HistoryError(f"non-finite stored JSON number {token!r} is not allowed")


def _decode_document(text: str, location: str) -> dict[str, Any]:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except HistoryError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise HistoryError(f"{location} is invalid JSON: {exc}") from exc
    if type(value) is not dict:
        raise HistoryError(f"{location} must contain one JSON object")
    if text != canonical_json(value) + "\n":
        raise HistoryError(f"{location} is not canonical JSON")
    return value


def _decode_successful_request(text: str) -> dict[str, Any]:
    value = json.loads(text, parse_float=float, parse_int=float)
    if type(value) is not dict:
        raise HistoryError("Metering accepted a request that is not an object")
    return value


def _measure(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    completed = subprocess.run(
        [sys.executable, "-m", "metering"],
        input=text,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode == 2 and not completed.stdout and completed.stderr:
        raise MeasurementRejected(completed.stderr)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit status {completed.returncode}"
        raise HistoryError(f"Metering failed: {detail}")
    if completed.stderr:
        raise HistoryError("Metering wrote to stderr for a successful request")

    try:
        request = _decode_successful_request(text)
        response = json.loads(completed.stdout)
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise HistoryError("Metering returned or accepted invalid JSON") from exc
    if type(response) is not dict:
        raise HistoryError("Metering returned a response that is not an object")
    if completed.stdout != canonical_json(response) + "\n":
        raise HistoryError("Metering returned non-canonical JSON")
    return request, response


def _git_environment(*, commit: bool = False) -> dict[str, str]:
    environment = os.environ.copy()
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["LC_ALL"] = "C"
    if commit:
        environment.update(
            {
                "GIT_AUTHOR_EMAIL": "metering@invalid",
                "GIT_AUTHOR_NAME": "Metering",
                "GIT_COMMITTER_EMAIL": "metering@invalid",
                "GIT_COMMITTER_NAME": "Metering",
            }
        )
    return environment


def _run_git(
    root: Path,
    arguments: Sequence[str],
    *,
    allowed_statuses: tuple[int, ...] = (0,),
    commit: bool = False,
) -> tuple[int, str]:
    command = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "commit.gpgSign=false",
        "-c",
        "core.autocrlf=false",
        "-c",
        f"core.attributesFile={os.devnull}",
        *arguments,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            env=_git_environment(commit=commit),
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise HistoryError(f"cannot run Git: {exc}") from exc
    if completed.returncode not in allowed_statuses:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise HistoryError(
            detail or f"Git exited with status {completed.returncode}"
        )
    return completed.returncode, completed.stdout


def _prepare_history(root: Path, *, create: bool) -> Path:
    root = root.absolute()
    if root.is_symlink():
        raise HistoryError(f"history directory may not be a symlink: {root}")
    if root.exists():
        if not root.is_dir():
            raise HistoryError(f"history path is not a directory: {root}")
    elif create:
        try:
            root.mkdir(parents=True)
        except OSError as exc:
            raise HistoryError(f"cannot create history directory {root}: {exc}") from exc
    else:
        raise HistoryError(f"history directory does not exist: {root}")

    git_directory = root / ".git"
    if git_directory.is_symlink():
        raise HistoryError(f"history Git directory may not be a symlink: {git_directory}")
    if not git_directory.exists():
        if not create:
            raise HistoryError(f"history is not a Git repository: {root}")
        try:
            entries = list(root.iterdir())
        except OSError as exc:
            raise HistoryError(f"cannot inspect history directory {root}: {exc}") from exc
        if entries:
            raise HistoryError(
                "history directory must be empty before Git initialization; "
                "legacy object histories require explicit migration"
            )
        _run_git(root, ["init", "--quiet"])
        _run_git(root, ["symbolic-ref", "HEAD", _HISTORY_BRANCH])
    elif not git_directory.is_dir():
        raise HistoryError(f"history .git is not a directory: {git_directory}")

    _, top_level = _run_git(root, ["rev-parse", "--show-toplevel"])
    try:
        actual_root = Path(top_level.strip()).resolve()
        expected_root = root.resolve()
    except OSError as exc:
        raise HistoryError(f"cannot resolve history repository path: {exc}") from exc
    if actual_root != expected_root:
        raise HistoryError("history path must be the root of its dedicated Git repository")
    status, branch = _run_git(
        root,
        ["symbolic-ref", "--quiet", "HEAD"],
        allowed_statuses=(0, 1),
    )
    if status != 0 or branch.strip() != _HISTORY_BRANCH:
        raise HistoryError("history must use the metering-history branch")
    return root


@contextmanager
def _locked(root: Path) -> Iterator[None]:
    lock = root / ".git" / "metering-history.lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise HistoryError(f"history is locked: {lock}") from exc
    except OSError as exc:
        raise HistoryError(f"cannot lock history {root}: {exc}") from exc
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError as exc:
            raise HistoryError(f"cannot remove history lock {lock}: {exc}") from exc


def _validate_git_id(value: object, *, field: str) -> str:
    if type(value) is not str or _GIT_OBJECT_ID(value) is None:
        raise HistoryError(f"{field} must be a lowercase Git object identifier")
    return value


def _head(root: Path) -> str | None:
    status, source = _run_git(
        root,
        ["rev-parse", "--verify", "--quiet", "HEAD"],
        allowed_statuses=(0, 1),
    )
    if status != 0:
        return None
    return _validate_git_id(source.strip(), field="history HEAD")


def _ensure_clean(root: Path) -> None:
    _, source = _run_git(root, ["status", "--porcelain=v1", "--untracked-files=all"])
    if source:
        first = source.splitlines()[0]
        raise HistoryError(f"history working tree is not clean: {first}")


def _write_file_atomically(path: Path, text: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise HistoryError(f"cannot write {path}: {exc}") from exc
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _storage_directories(root: Path) -> None:
    for relative in ("measurement", _PAIR_DIRECTORY):
        directory = root / relative
        if directory.is_symlink():
            raise HistoryError(f"history storage may not be a symlink: {directory}")
        if directory.exists() and not directory.is_dir():
            raise HistoryError(f"history storage is not a directory: {directory}")
        try:
            directory.mkdir(exist_ok=True)
        except OSError as exc:
            raise HistoryError(f"cannot create history storage {directory}: {exc}") from exc
    for relative in _EXPECTED_PATHS:
        path = root / relative
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise HistoryError(f"history storage is not a regular file: {path}")


def _implementation_sha256() -> str:
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256(b"metering-implementation-v1\x00")
    for path in sorted(package.glob("*.py"), key=lambda item: item.name):
        content = path.read_bytes()
        encoded_name = path.name.encode("utf-8")
        digest.update(str(len(encoded_name)).encode("ascii") + b":" + encoded_name)
        digest.update(str(len(content)).encode("ascii") + b":" + content)
    return digest.hexdigest()


def _source_state() -> tuple[str | None, bool]:
    project = Path(__file__).resolve().parents[2]
    if not (project / "pyproject.toml").is_file():
        return None, False
    try:
        completed = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "rev-parse", "HEAD"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            env=_git_environment(),
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            return None, False
        source_commit = completed.stdout.strip()
        if _GIT_OBJECT_ID(source_commit) is None:
            return None, False
        dirty = subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "status",
                "--porcelain=v1",
                "--untracked-files=no",
            ],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            env=_git_environment(),
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        return source_commit, dirty.returncode != 0 or bool(dirty.stdout)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None, False


def _provenance() -> dict[str, Any]:
    source_commit, source_dirty = _source_state()
    return {
        "implementation_sha256": _implementation_sha256(),
        "metering_version": __version__,
        "python_version": platform.python_version(),
        "schema_version": SCHEMA_VERSION,
        "source_commit": source_commit,
        "source_dirty": source_dirty,
    }


def _validate_provenance(value: dict[str, Any], location: str) -> dict[str, Any]:
    if set(value) != _PROVENANCE_KEYS:
        raise HistoryError(f"{location} has the wrong keys")
    if value["schema_version"] != SCHEMA_VERSION or type(
        value["schema_version"]
    ) is not int:
        raise HistoryError(f"{location} has an unsupported schema version")
    for field in ("metering_version", "python_version"):
        if type(value[field]) is not str or not value[field]:
            raise HistoryError(f"{location}.{field} must be a non-empty string")
    implementation = value["implementation_sha256"]
    if type(implementation) is not str or _SHA256(implementation) is None:
        raise HistoryError(
            f"{location}.implementation_sha256 must be a lowercase SHA-256 digest"
        )
    source_commit = value["source_commit"]
    if source_commit is not None:
        _validate_git_id(source_commit, field=f"{location}.source_commit")
    if type(value["source_dirty"]) is not bool:
        raise HistoryError(f"{location}.source_dirty must be a boolean")
    return value


def _tree_entries(root: Path, commit_id: str) -> dict[str, tuple[str, str]]:
    _, source = _run_git(root, ["ls-tree", "-r", "-z", commit_id])
    entries: dict[str, tuple[str, str]] = {}
    for raw_entry in source.split("\x00"):
        if not raw_entry:
            continue
        try:
            metadata, path = raw_entry.split("\t", 1)
            mode, object_type, _ = metadata.split(" ", 2)
        except ValueError as exc:
            raise HistoryError(f"record {commit_id} contains a malformed Git tree") from exc
        entries[path] = (mode, object_type)
    if tuple(sorted(entries)) != tuple(sorted(_EXPECTED_PATHS)):
        raise HistoryError(f"record {commit_id} has unexpected tracked files")
    for path, (mode, object_type) in entries.items():
        if mode != "100644" or object_type != "blob":
            raise HistoryError(f"record {commit_id} has an invalid file mode: {path}")
    return entries


def _show_file(root: Path, commit_id: str, path: str) -> str:
    _, source = _run_git(root, ["show", f"{commit_id}:{path}"])
    return source


def _record_from_commit(root: Path, commit_id: str) -> dict[str, Any]:
    commit_id = _validate_git_id(commit_id, field="record identifier")
    _, parent_source = _run_git(root, ["rev-list", "--parents", "-n", "1", commit_id])
    identifiers = parent_source.split()
    if not identifiers or identifiers[0] != commit_id or len(identifiers) > 2:
        raise HistoryError(f"record {commit_id} must have at most one parent")
    parent_id = None if len(identifiers) == 1 else _validate_git_id(
        identifiers[1], field=f"record {commit_id} parent"
    )

    _tree_entries(root, commit_id)
    configuration = _decode_document(
        _show_file(root, commit_id, _CONFIGURATION_PATH),
        f"record {commit_id} configuration",
    )
    result = _decode_document(
        _show_file(root, commit_id, _RESULT_PATH),
        f"record {commit_id} result",
    )
    provenance = _validate_provenance(
        _decode_document(
            _show_file(root, commit_id, _PROVENANCE_PATH),
            f"record {commit_id} provenance",
        ),
        f"record {commit_id} provenance",
    )
    if set(result) != _RESPONSE_KEYS:
        raise HistoryError(f"record {commit_id} has an invalid Metering result")
    if result.get("measure") != configuration.get("measure"):
        raise HistoryError(
            f"record {commit_id} configuration and result measures differ"
        )

    _, pair_source = _run_git(root, ["rev-parse", f"{commit_id}:{_PAIR_DIRECTORY}"])
    pair_id = _validate_git_id(pair_source.strip(), field=f"record {commit_id} pair")
    _, tree_source = _run_git(root, ["rev-parse", f"{commit_id}^{{tree}}"])
    tree_id = _validate_git_id(tree_source.strip(), field=f"record {commit_id} tree")
    return {
        **provenance,
        "pair_id": pair_id,
        "parent_record_id": parent_id,
        "record_id": commit_id,
        "request": configuration,
        "response": result,
        "tree_id": tree_id,
    }


def _history_log(root: Path) -> tuple[str | None, list[dict[str, Any]]]:
    head = _head(root)
    if head is None:
        return None, []
    _, source = _run_git(root, ["rev-list", "--first-parent", "HEAD"])
    commit_ids = [line for line in source.splitlines() if line]
    records = [_record_from_commit(root, commit_id) for commit_id in commit_ids]
    for index, record in enumerate(records):
        expected_parent = records[index + 1]["record_id"] if index + 1 < len(records) else None
        if record["parent_record_id"] != expected_parent:
            raise HistoryError(f"record {record['record_id']} has an invalid parent")
    return head, records


def _write_snapshot(
    root: Path,
    request: dict[str, Any],
    response: dict[str, Any],
) -> None:
    _storage_directories(root)
    documents = {
        _CONFIGURATION_PATH: request,
        _RESULT_PATH: response,
        _PROVENANCE_PATH: _provenance(),
    }
    for relative, document in documents.items():
        _write_file_atomically(root / relative, canonical_json(document) + "\n")
    _run_git(root, ["add", "--force", "--", *_EXPECTED_PATHS])


def record_measurement(
    root: Path, request: dict[str, Any], response: dict[str, Any]
) -> dict[str, Any]:
    root = _prepare_history(root, create=True)
    with _locked(root):
        _ensure_clean(root)
        parent, _ = _history_log(root)
        _write_snapshot(root, request, response)
        measure = response.get("measure")
        message = f"Record {measure} measurement" if type(measure) is str else "Record measurement"
        _run_git(
            root,
            ["commit", "--quiet", "--allow-empty", "--no-gpg-sign", "-m", message],
            commit=True,
        )
        record_id = _head(root)
        if record_id is None:
            raise HistoryError("Git did not create a measurement commit")
        record = _record_from_commit(root, record_id)
        if record["parent_record_id"] != parent:
            raise HistoryError("Git measurement commit has an unexpected parent")
        _ensure_clean(root)
    return record


def history_log(root: Path) -> tuple[str | None, list[dict[str, Any]]]:
    root = _prepare_history(root, create=False)
    return _history_log(root)


def verify_history(root: Path) -> dict[str, Any]:
    root = _prepare_history(root, create=False)
    lock = root / ".git" / "metering-history.lock"
    if lock.exists():
        raise HistoryError(f"history is locked: {lock}")
    _ensure_clean(root)
    _run_git(root, ["fsck", "--full", "--no-dangling"])
    head, records = _history_log(root)
    for record in reversed(records):
        source = canonical_json(record["request"]) + "\n"
        try:
            request, response = _measure(source)
        except MeasurementRejected as exc:
            raise HistoryError(
                f"record {record['record_id']} configuration is rejected by Metering"
            ) from exc
        if request != record["request"]:
            raise HistoryError(
                f"record {record['record_id']} configuration is not normalized"
            )
        if response != record["response"]:
            raise HistoryError(
                f"record {record['record_id']} result does not match Metering replay"
            )
    return {"head": head, "records": len(records), "valid": True}


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if arguments.command == "record":
            request, response = _measure(sys.stdin.read())
            result = record_measurement(arguments.history, request, response)
        elif arguments.command == "log":
            head, records = history_log(arguments.history)
            result = {"head": head, "records": records}
        else:
            result = verify_history(arguments.history)
    except CommandError as exc:
        _write_error("invalid_request", str(exc))
        return 2
    except MeasurementRejected as exc:
        sys.stderr.write(exc.stderr)
        return 2
    except HistoryError as exc:
        _write_error("invalid_history", str(exc))
        return 2

    _write_json(sys.stdout, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
