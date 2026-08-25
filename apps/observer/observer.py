"""Observe a versioned folder by calling Metering as a JSON subprocess tool."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
FIXTURES_ROOT = APP_ROOT / "fixtures"
VERSIONS_PATH = APP_ROOT / "versions.json"


PROTOCOL_VERSION = 1


class ObserverError(RuntimeError):
    """Raised when the example cannot produce a valid observation."""


class AgentRequestError(ValueError):
    """Raised when one JSONL agent request is malformed or out of order."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ObserverError(f"invalid command line: {message}")


@dataclass(frozen=True)
class Version:
    name: str
    parent: str | None
    parent_snapshot_id: str | None
    root: Path
    paths: tuple[str, ...]
    tree_id: str
    snapshot_id: str

    def identity(self) -> dict[str, object]:
        return {
            "name": self.name,
            "parent": self.parent,
            "parent_snapshot_id": self.parent_snapshot_id,
            "snapshot_id": self.snapshot_id,
            "tree_id": self.tree_id,
        }


@dataclass(frozen=True)
class Probe:
    operation: str
    path: str | None = None

    def document(self) -> dict[str, str]:
        document = {"operation": self.operation}
        if self.path is not None:
            document["path"] = self.path
        return document


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def fixture_manifest(root: Path) -> list[dict[str, object]]:
    manifest: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ObserverError(f"fixture may not contain a symlink: {path}")
        if not path.is_file():
            continue
        content = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ObserverError(f"fixture is not UTF-8 text: {relative}") from exc
        manifest.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
        )
    if not manifest:
        raise ObserverError(f"fixture has no files: {root}")
    return manifest


def load_versions() -> tuple[Version, ...]:
    try:
        metadata = json.loads(VERSIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObserverError(f"cannot read {VERSIONS_PATH}: {exc}") from exc
    if type(metadata) is not list or not metadata:
        raise ObserverError("versions.json must contain a non-empty array")

    versions: list[Version] = []
    by_name: dict[str, Version] = {}
    tree_ids: set[str] = set()
    for item in metadata:
        if type(item) is not dict or set(item) != {"name", "parent"}:
            raise ObserverError("each version must contain exactly name and parent")
        name = item["name"]
        parent = item["parent"]
        if (
            type(name) is not str
            or not name
            or name in {".", ".."}
            or "\x00" in name
            or Path(name).name != name
        ):
            raise ObserverError("version name must be one path component")
        if name in by_name:
            raise ObserverError(f"duplicate version: {name}")
        if parent is not None and type(parent) is not str:
            raise ObserverError(
                "version parent must be null or a preceding version name"
            )
        if parent is not None and parent not in by_name:
            raise ObserverError(f"parent must precede its child: {parent}")

        root = FIXTURES_ROOT / name
        if root.is_symlink():
            raise ObserverError(f"fixture directory may not be a symlink: {root}")
        if not root.is_dir():
            raise ObserverError(f"missing fixture directory: {root}")
        manifest = fixture_manifest(root)
        tree_id = digest(manifest)
        if tree_id in tree_ids:
            raise ObserverError(
                f"fixture is indistinguishable from an earlier one: {name}"
            )
        tree_ids.add(tree_id)
        parent_snapshot_id = None if parent is None else by_name[parent].snapshot_id
        snapshot_id = digest(
            {"parent_snapshot_id": parent_snapshot_id, "tree_id": tree_id}
        )
        version = Version(
            name=name,
            parent=parent,
            parent_snapshot_id=parent_snapshot_id,
            root=root,
            paths=tuple(str(entry["path"]) for entry in manifest),
            tree_id=tree_id,
            snapshot_id=snapshot_id,
        )
        versions.append(version)
        by_name[name] = version
    return tuple(versions)


def sandbox_root(root: Path) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise ObserverError(f"sandbox root must be a real directory: {root}")
    try:
        return root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ObserverError(f"cannot resolve sandbox root: {root}") from exc


def read_probe_path(root: Path, value: str) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        raise ObserverError("probe path must be a non-empty relative path")
    relative = Path(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {".", ".."} for part in relative.parts)
    ):
        raise ObserverError(f"probe path must be normalized and relative: {value}")

    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise ObserverError(f"probe path may not traverse a symlink: {value}")
    try:
        resolved = path.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ObserverError(f"probe path escapes the sandbox: {value}") from exc
    return resolved


def observe(root: Path, probe: Probe) -> dict[str, object]:
    root = sandbox_root(root)
    if probe.operation == "list":
        if probe.path is not None:
            raise ObserverError("list probe may not contain a path")
        paths: list[str] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                relative = path.relative_to(root).as_posix()
                raise ObserverError(f"sandbox may not contain a symlink: {relative}")
            if path.is_file():
                paths.append(path.relative_to(root).as_posix())
        return {"kind": "listing", "paths": paths}

    if probe.operation != "read" or probe.path is None:
        raise ObserverError(f"unsupported probe: {probe}")
    path = read_probe_path(root, probe.path)
    if not path.is_file():
        return {"kind": "missing"}
    try:
        content = path.read_bytes()
        return {"kind": "text", "text": content.decode("utf-8")}
    except UnicodeDecodeError as exc:
        raise ObserverError(f"sandbox file is not UTF-8 text: {probe.path}") from exc


def available_probes(versions: tuple[Version, ...]) -> tuple[Probe, ...]:
    paths = sorted({path for version in versions for path in version.paths})
    return (Probe("list"), *(Probe("read", path) for path in paths))


def outcomes(
    versions: tuple[Version, ...], probe: Probe
) -> tuple[dict[str, object], ...]:
    groups: dict[str, dict[str, object]] = {}
    for version in versions:
        result = observe(version.root, probe)
        key = canonical_json(result)
        group = groups.setdefault(key, {"result": result, "versions": []})
        group["versions"].append(version.name)

    return tuple(
        {
            "probability": len(group["versions"]) / len(versions),
            **group,
        }
        for _, group in sorted(groups.items())
    )


def call_metering(
    measure: str, *, history: Path | None = None, **arguments: object
) -> dict[str, object]:
    request = {"measure": measure, **arguments}
    command = [sys.executable, "-m", "metering"]
    if history is not None:
        command = [
            sys.executable,
            "-m",
            "metering.history",
            "record",
            str(history),
        ]
    completed = subprocess.run(
        command,
        input=canonical_json(request) + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit status {completed.returncode}"
        raise ObserverError(f"Metering rejected {request}: {detail}")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ObserverError("Metering returned invalid JSON") from exc
    if history is not None:
        try:
            if response["request"] != request:
                raise ObserverError("measurement history changed the Metering request")
            return {
                "history": {
                    "pair_id": response["pair_id"],
                    "parent_record_id": response["parent_record_id"],
                    "record_id": response["record_id"],
                },
                "request": request,
                "response": response["response"],
            }
        except (KeyError, TypeError) as exc:
            raise ObserverError(
                "measurement history response has the wrong shape"
            ) from exc
    return {"request": request, "response": response}


def entropy(
    probabilities: list[float], *, history: Path | None = None
) -> dict[str, object]:
    return call_metering(
        "entropy", probabilities=probabilities, history=history
    )


def uniform_entropy(
    count: int, *, history: Path | None = None
) -> dict[str, object]:
    return entropy([1.0 / count] * count, history=history)


def probe_score(
    versions: tuple[Version, ...], probe: Probe, *, history: Path | None = None
) -> dict[str, object]:
    possible_outcomes = outcomes(versions, probe)
    measurement = entropy(
        [float(outcome["probability"]) for outcome in possible_outcomes],
        history=history,
    )
    return {
        "measurement": measurement,
        "outcomes": possible_outcomes,
        "probe": probe.document(),
    }


def score_value(score: dict[str, object]) -> float:
    try:
        value = score["measurement"]["response"]["value"]
    except (KeyError, TypeError) as exc:
        raise ObserverError("Metering entropy response has the wrong shape") from exc
    if type(value) is not float:
        raise ObserverError("Metering entropy response has no finite value")
    return value


def emit(document: dict[str, object]) -> None:
    print(canonical_json(document), flush=True)


def _write_agent_json(stream: object, document: dict[str, object]) -> None:
    stream.write(
        json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    stream.flush()


def _agent_error(catalogue_id: str, step: int, message: str) -> dict[str, object]:
    return {
        "catalogue_id": catalogue_id,
        "error": {"code": "invalid_request", "message": message},
        "ok": False,
        "protocol_version": PROTOCOL_VERSION,
        "step": step,
    }


def _agent_unique_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AgentRequestError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_agent_nonfinite(token: str) -> None:
    raise AgentRequestError(f"non-finite JSON number {token!r} is not allowed")


def _require_agent_keys(
    value: dict[str, object], expected: set[str], location: str
) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing keys: {', '.join(missing)}")
    if extra:
        details.append(f"extra keys: {', '.join(extra)}")
    if details:
        raise AgentRequestError(f"{location}: {'; '.join(details)}")


def decode_agent_request(source: str) -> dict[str, object]:
    """Decode one strict Observer JSONL action."""

    if not source.strip():
        raise AgentRequestError("request line must contain one JSON object")
    try:
        request = json.loads(
            source,
            object_pairs_hook=_agent_unique_object,
            parse_constant=_reject_agent_nonfinite,
        )
    except AgentRequestError:
        raise
    except json.JSONDecodeError as exc:
        raise AgentRequestError(
            f"invalid JSON at column {exc.colno}: {exc.msg}"
        ) from exc
    except (RecursionError, ValueError) as exc:
        raise AgentRequestError(f"invalid JSON: {exc}") from exc
    if type(request) is not dict:
        raise AgentRequestError("request must be one JSON object")

    action = request.get("action")
    if type(action) is not str or action not in {"finish", "observe", "state"}:
        raise AgentRequestError("action must be one of: finish, observe, state")
    if action == "state":
        _require_agent_keys(request, {"action"}, "request")
    elif action == "finish":
        _require_agent_keys(request, {"action", "snapshot_id"}, "request")
        snapshot_id = request["snapshot_id"]
        if (
            type(snapshot_id) is not str
            or len(snapshot_id) != 64
            or any(character not in "0123456789abcdef" for character in snapshot_id)
        ):
            raise AgentRequestError(
                "snapshot_id must be a lowercase SHA-256 identifier"
            )
    else:
        _require_agent_keys(request, {"action", "probe"}, "request")
        probe = request["probe"]
        if type(probe) is not dict:
            raise AgentRequestError("probe must be one JSON object")
        operation = probe.get("operation")
        if operation == "list":
            _require_agent_keys(probe, {"operation"}, "probe")
        elif operation == "read":
            _require_agent_keys(probe, {"operation", "path"}, "probe")
            if type(probe["path"]) is not str or not probe["path"]:
                raise AgentRequestError("probe.path must be a non-empty string")
        else:
            raise AgentRequestError("probe.operation must be one of: list, read")
    return request


def _measurement_response(measurement: dict[str, object]) -> dict[str, object]:
    response = measurement.get("response")
    if type(response) is not dict:
        raise ObserverError("Metering response has the wrong shape")
    return response


def _belief(
    versions: tuple[Version, ...], candidates: tuple[Version, ...]
) -> dict[str, float]:
    candidate_names = {version.name for version in candidates}
    probability = 1.0 / len(candidates)
    return {
        version.name: probability if version.name in candidate_names else 0.0
        for version in versions
    }


def _agent_snapshot(version: Version) -> dict[str, str]:
    return {
        "name": version.name,
        "snapshot_id": version.snapshot_id,
        "tree_id": version.tree_id,
    }


def run_agent_session(
    versions: tuple[Version, ...],
    sandbox: Path,
    *,
    history: Path | None = None,
) -> None:
    """Process one stateful external-agent session as JSON Lines."""

    sandbox = sandbox_root(sandbox)
    catalogue = available_probes(versions)
    catalogue_documents = [probe.document() for probe in catalogue]
    catalogue_keys = {canonical_json(document) for document in catalogue_documents}
    catalogue_id = digest({"probes": catalogue_documents})
    candidates = versions
    step = 0
    finished = False
    binary_input = getattr(sys.stdin, "buffer", None)

    while True:
        invalid_utf8 = False
        try:
            if binary_input is None:
                source = sys.stdin.readline()
                if source == "":
                    break
            else:
                raw = binary_input.readline()
                if raw == b"":
                    break
                try:
                    source = raw.decode("utf-8")
                except UnicodeDecodeError:
                    source = ""
                    invalid_utf8 = True
        except OSError as exc:
            raise ObserverError(f"cannot read agent input: {exc}") from exc

        try:
            if invalid_utf8:
                raise AgentRequestError("request line must be valid UTF-8 JSON")
            request = decode_agent_request(source)
            if finished:
                raise AgentRequestError("session is already finished")
            action = request["action"]

            if action == "state":
                available = []
                for probe in catalogue:
                    score = probe_score(candidates, probe, history=history)
                    available.append(
                        {
                            "probe": probe.document(),
                            "result_entropy": _measurement_response(
                                score["measurement"]
                            ),
                        }
                    )
                response = {
                    "available_probes": available,
                    "belief": _belief(versions, candidates),
                    "catalogue_id": catalogue_id,
                    "ok": True,
                    "protocol_version": PROTOCOL_VERSION,
                    "snapshots": [_agent_snapshot(version) for version in versions],
                    "step": step,
                }
            elif action == "observe":
                if len(candidates) == 1:
                    raise AgentRequestError(
                        "belief is complete; finish the session instead"
                    )
                probe_document = request["probe"]
                if canonical_json(probe_document) not in catalogue_keys:
                    raise AgentRequestError(
                        "probe is not in the immutable observation catalogue"
                    )
                probe = Probe(
                    probe_document["operation"], probe_document.get("path")
                )
                entropy_before = _measurement_response(
                    uniform_entropy(len(candidates), history=history)
                )
                result = observe(sandbox, probe)
                result_key = canonical_json(result)
                matching = tuple(
                    version
                    for version in candidates
                    if canonical_json(observe(version.root, probe)) == result_key
                )
                if not matching:
                    raise ObserverError(
                        "sandbox result matches no candidate version"
                    )
                probability = len(matching) / len(candidates)
                entropy_after = _measurement_response(
                    uniform_entropy(len(matching), history=history)
                )
                surprisal = _measurement_response(
                    call_metering(
                        "self_information",
                        probability=probability,
                        history=history,
                    )
                )
                candidates = matching
                step += 1
                response = {
                    "belief": _belief(versions, candidates),
                    "belief_entropy_after": entropy_after,
                    "belief_entropy_before": entropy_before,
                    "catalogue_id": catalogue_id,
                    "done": len(candidates) == 1,
                    "observed_probability": probability,
                    "observed_result": result,
                    "observed_surprisal": surprisal,
                    "ok": True,
                    "protocol_version": PROTOCOL_VERSION,
                    "step": step,
                }
            else:
                if len(candidates) != 1:
                    raise AgentRequestError(
                        "finish requires exactly one remaining candidate"
                    )
                identified = candidates[0]
                sandbox_tree_id = digest(fixture_manifest(sandbox))
                if sandbox_tree_id != identified.tree_id:
                    raise ObserverError(
                        "sandbox tree does not match identified snapshot"
                    )
                response = {
                    "catalogue_id": catalogue_id,
                    "correct": request["snapshot_id"] == identified.snapshot_id,
                    "ok": True,
                    "protocol_version": PROTOCOL_VERSION,
                    "snapshot": _agent_snapshot(identified),
                    "step": step,
                }
                finished = True
        except AgentRequestError as exc:
            response = _agent_error(catalogue_id, step, str(exc))

        _write_agent_json(sys.stdout, response)


def run(
    versions: tuple[Version, ...],
    sandbox: Path,
    *,
    history: Path | None = None,
) -> Version:
    sandbox = sandbox_root(sandbox)
    emit(
        {
            "event": "start",
            "model": {
                "candidate_prior": "uniform",
                "probability_rule": "matching_versions / remaining_versions",
            },
            "versions": [version.identity() for version in versions],
        }
    )

    candidates = versions
    step = 0
    while len(candidates) > 1:
        step += 1
        scores = [
            probe_score(candidates, probe, history=history)
            for probe in available_probes(candidates)
        ]
        selected = max(scores, key=score_value)
        if score_value(selected) == 0.0:
            raise ObserverError("remaining versions cannot be distinguished")

        probe_data = selected["probe"]
        probe = Probe(probe_data["operation"], probe_data.get("path"))
        result = observe(sandbox, probe)
        result_key = canonical_json(result)
        matching = tuple(
            version
            for version in candidates
            if canonical_json(observe(version.root, probe)) == result_key
        )
        if not matching:
            raise ObserverError("sandbox result matches no candidate version")
        probability = len(matching) / len(candidates)

        emit(
            {
                "candidate_entropy_after": uniform_entropy(
                    len(matching), history=history
                ),
                "candidate_entropy_before": uniform_entropy(
                    len(candidates), history=history
                ),
                "candidates_after": [version.name for version in matching],
                "candidates_before": [version.name for version in candidates],
                "event": "observation",
                "observed_probability": probability,
                "observed_result": result,
                "observed_surprisal": call_metering(
                    "self_information", probability=probability, history=history
                ),
                "probe_scores": scores,
                "selected_probe": probe.document(),
                "step": step,
            }
        )
        candidates = matching

    identified = candidates[0]
    sandbox_tree_id = digest(fixture_manifest(sandbox))
    if sandbox_tree_id != identified.tree_id:
        raise ObserverError("sandbox tree does not match identified snapshot")
    emit({"event": "identified", "snapshot": identified.identity(), "steps": step})
    return identified


def _report_main_error(message: str, *, jsonl: bool) -> int:
    if jsonl:
        _write_agent_json(
            sys.stderr,
            {"error": {"code": "observer_error", "message": message}},
        )
    else:
        print(f"observer: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    if raw_arguments == ["--evaluate"]:
        observer_root = str(Path(__file__).resolve().parent)
        if observer_root not in sys.path:
            sys.path.insert(0, observer_root)
        from agent_evaluator import main as evaluator_main

        return evaluator_main()

    jsonl_requested = "--jsonl" in raw_arguments
    try:
        versions = load_versions()
        parser = _ArgumentParser(
            description="Identify a versioned text sandbox using Metering.",
            allow_abbrev=False,
        )
        parser.add_argument(
            "--active",
            choices=[version.name for version in versions],
            default=versions[0].name,
            help="fixture version to materialize (default: %(default)s)",
        )
        parser.add_argument(
            "--history",
            type=Path,
            help="append every Metering request/response pair to this history",
        )
        parser.add_argument(
            "--jsonl",
            action="store_true",
            help="serve one external-agent action per JSON line",
        )
        arguments = parser.parse_args(raw_arguments)
        active_name = arguments.active
        active = next(version for version in versions if version.name == active_name)

        with tempfile.TemporaryDirectory(prefix="metering-observer-") as temp:
            sandbox = Path(temp) / "sandbox"
            shutil.copytree(active.root, sandbox)
            if arguments.jsonl:
                run_agent_session(
                    versions,
                    sandbox,
                    history=arguments.history,
                )
                return 0
            identified = run(versions, sandbox, history=arguments.history)
        if identified.snapshot_id != active.snapshot_id:
            raise ObserverError("identified snapshot does not match active snapshot")
    except ObserverError as exc:
        return _report_main_error(str(exc), jsonl=jsonl_requested)
    except OSError as exc:
        return _report_main_error(
            f"operating system failure: {exc}",
            jsonl=jsonl_requested,
        )
    except Exception as exc:
        if not jsonl_requested:
            raise
        detail = str(exc) or type(exc).__name__
        return _report_main_error(
            f"internal controller failure: {detail}",
            jsonl=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
