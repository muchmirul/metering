from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

import pytest


def _run(api, tmp_path, name="strict-schema"):
    return api.run(
        harness=api.policy("balanced"),
        fault_id=api.fault_ids[1],
        parent_dir=tmp_path,
        budget=16,
        run_id=name,
    )


def _encode_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _encode_events(values: list[dict[str, Any]]) -> bytes:
    return b"".join(_encode_json(value) for value in values)


def _reject_bytes(api, run, filename: str, damaged: bytes, label: str) -> None:
    path = run.run_dir / filename
    baseline = path.read_bytes()
    try:
        path.write_bytes(damaged)
        (run.run_dir / "report.json").unlink(missing_ok=True)
        try:
            api.rebuild_report(run.run_dir)
        except ValueError:
            pass
        else:
            pytest.fail(f"accepted corrupt {filename}: {label}")
        assert not (run.run_dir / "report.json").exists()
    finally:
        path.write_bytes(baseline)
        (run.run_dir / "report.json").unlink(missing_ok=True)


def _remove_path(document: dict[str, Any], path: tuple[str, ...]) -> None:
    target: Any = document
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]


def _set_path(document: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target: Any = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _mapping_child_paths(document: dict[str, Any], roots: tuple[str, ...]):
    paths: list[tuple[str, ...]] = []

    def visit(value: Any, prefix: tuple[str, ...]) -> None:
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            path = prefix + (key,)
            paths.append(path)
            if isinstance(child, dict):
                visit(child, path)

    for root in roots:
        if root in document and isinstance(document[root], dict):
            visit(document[root], (root,))
    return paths


def _all_mapping_paths(document: dict[str, Any]) -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = [()]

    def visit(value: dict[str, Any], prefix: tuple[str, ...]) -> None:
        for key, child in value.items():
            if isinstance(child, dict):
                path = prefix + (key,)
                paths.append(path)
                visit(child, path)

    visit(document, ())
    return paths


def test_every_manifest_root_and_nested_contract_field_is_required(api, tmp_path):
    run = _run(api, tmp_path, "manifest-required")
    manifest = run.manifest
    paths = [(key,) for key in manifest]
    paths += _mapping_child_paths(
        manifest,
        tuple(key for key, value in manifest.items() if isinstance(value, dict)),
    )
    # Exercise object fields nested inside catalogue lists as well as mappings.
    for catalogue_path in (
        ("instance", "diagnostic_tests"),
        ("world_specification", "diagnostic_tests"),
    ):
        try:
            tests: Any = manifest
            for key in catalogue_path:
                tests = tests[key]
        except KeyError:
            continue
        if tests and isinstance(tests[0], dict):
            paths.extend(catalogue_path + ("0", key) for key in tests[0])

    for path in paths:
        damaged = deepcopy(manifest)
        if "0" in path:
            list_index = path.index("0")
            target: Any = damaged
            for key in path[:list_index]:
                target = target[key]
            del target[0][path[-1]]
        else:
            _remove_path(damaged, path)
        _reject_bytes(api, run, "manifest.json", _encode_json(damaged), f"missing {path}")

    api.rebuild_report(run.run_dir)


def test_manifest_rejects_extra_root_nested_and_catalogue_fields(api, tmp_path):
    run = _run(api, tmp_path, "manifest-extra")
    manifest = run.manifest
    targets = _all_mapping_paths(manifest)

    for target_path in targets:
        damaged = deepcopy(manifest)
        target: Any = damaged
        for key in target_path:
            target = target[key]
        target["__unexpected_field__"] = "must be rejected"
        _reject_bytes(
            api,
            run,
            "manifest.json",
            _encode_json(damaged),
            f"extra field at {target_path or ('root',)}",
        )

    for catalogue_path in (
        ("instance", "diagnostic_tests"),
        ("world_specification", "diagnostic_tests"),
    ):
        damaged = deepcopy(manifest)
        try:
            tests: Any = damaged
            for key in catalogue_path:
                tests = tests[key]
        except KeyError:
            continue
        tests[0]["__unexpected_field__"] = True
        _reject_bytes(
            api,
            run,
            "manifest.json",
            _encode_json(damaged),
            f"extra catalogue field at {catalogue_path}",
        )

    api.rebuild_report(run.run_dir)


def test_every_reference_root_and_nested_field_is_required(api, tmp_path):
    run = _run(api, tmp_path, "reference-required")
    reference = run.reference
    paths = [(key,) for key in reference]
    paths += _mapping_child_paths(
        reference,
        tuple(key for key, value in reference.items() if isinstance(value, dict)),
    )

    for path in paths:
        damaged = deepcopy(reference)
        _remove_path(damaged, path)
        _reject_bytes(api, run, "reference.json", _encode_json(damaged), f"missing {path}")

    api.rebuild_report(run.run_dir)


def test_reference_rejects_extra_root_and_nested_fields(api, tmp_path):
    run = _run(api, tmp_path, "reference-extra")
    reference = run.reference
    targets = _all_mapping_paths(reference)
    for target_path in targets:
        damaged = deepcopy(reference)
        target: Any = damaged
        for key in target_path:
            target = target[key]
        target["__unexpected_field__"] = "must be rejected"
        _reject_bytes(
            api,
            run,
            "reference.json",
            _encode_json(damaged),
            f"extra field at {target_path or ('root',)}",
        )

    api.rebuild_report(run.run_dir)


def _duplicate_root_key(text: str, key: str) -> str:
    parsed = json.loads(text)
    assert key in parsed and text.lstrip().startswith("{")
    leading = len(text) - len(text.lstrip())
    prefix = text[:leading]
    body = text[leading:]
    duplicate = json.dumps(key) + ":" + json.dumps(parsed[key], separators=(",", ":")) + ","
    return prefix + "{" + duplicate + body[1:]


@pytest.mark.parametrize("filename,key", [
    ("manifest.json", "schema_version"),
    ("reference.json", "schema_version"),
    ("events.jsonl", "schema_version"),
])
def test_duplicate_json_object_keys_are_rejected(api, tmp_path, filename, key):
    run = _run(api, tmp_path, f"duplicate-{filename.replace('.', '-')}")
    path = run.run_dir / filename
    if filename == "events.jsonl":
        lines = path.read_text().splitlines(keepends=True)
        lines[0] = _duplicate_root_key(lines[0], key)
        damaged = "".join(lines).encode()
    else:
        damaged = _duplicate_root_key(path.read_text(), key).encode()
    _reject_bytes(api, run, filename, damaged, f"duplicate key {key}")


def test_nested_duplicate_json_key_is_rejected(api, tmp_path):
    run = _run(api, tmp_path, "duplicate-nested")
    path = run.run_dir / "manifest.json"
    text = path.read_text()
    name = run.manifest["policy"]["name"]
    needle = '"name":' + json.dumps(name, separators=(",", ":"))
    assert text.count(needle) == 1
    damaged = text.replace(needle, needle + "," + needle, 1).encode()
    _reject_bytes(api, run, "manifest.json", damaged, "duplicate nested policy.name")


def _replacement(original: int, kind: str):
    assert isinstance(original, int) and not isinstance(original, bool)
    return bool(original) if kind == "bool" else float(original)


@pytest.mark.parametrize("replacement_kind", ["bool", "equal_float"])
def test_bool_and_equal_float_are_rejected_for_every_integer_schema_or_count(
    api, tmp_path, replacement_kind
):
    run = _run(api, tmp_path, f"integer-types-{replacement_kind}")

    manifest_cases = [
        ("schema_version",),
        ("controller", "action_budget"),
        ("instance", "schema_version"),
    ]
    for path in manifest_cases:
        damaged = deepcopy(run.manifest)
        original: Any = damaged
        for key in path:
            original = original[key]
        _set_path(damaged, path, _replacement(original, replacement_kind))
        _reject_bytes(
            api, run, "manifest.json", _encode_json(damaged), f"{path} as {replacement_kind}"
        )

    reference_cases = [("schema_version",)]
    for key in ("repair_count", "verification_count", "actions_applied"):
        if key in run.reference.get("final_world_state", {}):
            reference_cases.append(("final_world_state", key))
    for path in reference_cases:
        damaged = deepcopy(run.reference)
        original: Any = damaged
        for key in path:
            original = original[key]
        _set_path(damaged, path, _replacement(original, replacement_kind))
        _reject_bytes(
            api, run, "reference.json", _encode_json(damaged), f"{path} as {replacement_kind}"
        )

    baseline_events = run.events
    event_cases: list[tuple[int, tuple[str, ...]]] = [
        (0, ("schema_version",)),
        (0, ("step",)),
    ]
    interaction_index = next(
        index for index, event in enumerate(baseline_events) if event["event_type"] == "interaction"
    )
    termination_index = next(
        index for index, event in enumerate(baseline_events) if event["event_type"] == "termination"
    )
    event_cases.extend(
        [
            (interaction_index, ("resources", "total_actions")),
            (termination_index, ("payload", "actions_used")),
            (termination_index, ("payload", "action_budget")),
        ]
    )
    for index, path in event_cases:
        damaged = deepcopy(baseline_events)
        original: Any = damaged[index]
        for key in path:
            original = original[key]
        _set_path(damaged[index], path, _replacement(original, replacement_kind))
        _reject_bytes(
            api,
            run,
            "events.jsonl",
            _encode_events(damaged),
            f"event {index} {path} as {replacement_kind}",
        )

    api.rebuild_report(run.run_dir)
