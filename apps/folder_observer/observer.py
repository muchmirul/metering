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


class ObserverError(RuntimeError):
    """Raised when the example cannot produce a valid observation."""


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
        if type(name) is not str or Path(name).name != name or not name:
            raise ObserverError("version name must be one path component")
        if name in by_name:
            raise ObserverError(f"duplicate version: {name}")
        if parent is not None and parent not in by_name:
            raise ObserverError(f"parent must precede its child: {parent}")

        root = FIXTURES_ROOT / name
        if not root.is_dir():
            raise ObserverError(f"missing fixture directory: {root}")
        manifest = fixture_manifest(root)
        tree_id = digest(manifest)
        if tree_id in tree_ids:
            raise ObserverError(f"fixture is indistinguishable from an earlier one: {name}")
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


def observe(root: Path, probe: Probe) -> dict[str, object]:
    if probe.operation == "list":
        paths = [
            path.relative_to(root).as_posix()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        ]
        return {"kind": "listing", "paths": paths}

    if probe.operation != "read" or probe.path is None:
        raise ObserverError(f"unsupported probe: {probe}")
    path = root / probe.path
    if not path.is_file():
        return {"kind": "missing"}
    try:
        return {"kind": "text", "text": path.read_text(encoding="utf-8")}
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
            raise ObserverError("measurement history response has the wrong shape") from exc
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


def run(
    versions: tuple[Version, ...],
    sandbox: Path,
    *,
    history: Path | None = None,
) -> Version:
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
    emit({"event": "identified", "snapshot": identified.identity(), "steps": step})
    return identified


def main(argv: list[str] | None = None) -> int:
    try:
        versions = load_versions()
        parser = argparse.ArgumentParser(
            description="Identify a versioned text sandbox using Metering."
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
        arguments = parser.parse_args(argv)
        active_name = arguments.active
        active = next(version for version in versions if version.name == active_name)

        with tempfile.TemporaryDirectory(prefix="metering-folder-observer-") as temp:
            sandbox = Path(temp) / "sandbox"
            shutil.copytree(active.root, sandbox)
            identified = run(versions, sandbox, history=arguments.history)
        if identified.snapshot_id != active.snapshot_id:
            raise ObserverError("identified snapshot does not match active snapshot")
    except ObserverError as exc:
        print(f"folder observer: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
