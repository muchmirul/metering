"""Run one fixed candidate model against an Observer probe."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from decimal import Decimal, InvalidOperation

from metering import ProbabilityError, entropy


SCHEMA_VERSION = 1
RUNNER_MODEL = "observer-fixture-hypothesis-v1"
MIN_CONFIDENCE_BPS = 2500
MAX_CONFIDENCE_BPS = 10000
VERSIONS = ("v1", "v2", "v3", "v4")
PATHS = ("config/mode.txt", "service/port.txt")
CONTENTS = {
    "v1": {"config/mode.txt": "safe\n", "service/port.txt": "8000\n"},
    "v2": {"config/mode.txt": "safe\n", "service/port.txt": "9000\n"},
    "v3": {"config/mode.txt": "fast\n", "service/port.txt": "8000\n"},
    "v4": {"config/mode.txt": "fast\n", "service/port.txt": "9000\n"},
}
CANDIDATE_ID_PATTERN = re.compile(r"[0-9a-f]{64}")


class RequestError(ValueError):
    """Raised when a runner request violates the application contract."""


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RequestError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_non_finite(token: str) -> object:
    raise RequestError(f"non-finite number is not valid JSON: {token}")


def _decode_json(source: str) -> dict[str, object]:
    if not source.strip():
        raise RequestError("stdin must contain one JSON object")
    try:
        request = json.loads(
            source,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite,
            parse_float=Decimal,
        )
    except RequestError:
        raise
    except json.JSONDecodeError as exc:
        raise RequestError(f"invalid JSON: {exc.msg}") from exc
    except (InvalidOperation, RecursionError, ValueError) as exc:
        raise RequestError(f"invalid JSON: {exc}") from exc
    if type(request) is not dict:
        raise RequestError("request must be one JSON object")
    return request


def _require_exact_keys(
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
        raise RequestError(f"{location}: {'; '.join(details)}")


def _require_nonempty_string(value: object, location: str) -> str:
    if type(value) is not str or not value:
        raise RequestError(f"{location} must be a non-empty string")
    return value


def _decode_genome(raw_genome: object) -> dict[str, object]:
    if type(raw_genome) is not dict:
        raise RequestError("genome must be a JSON object")
    _require_exact_keys(
        raw_genome,
        {"hypothesis", "hypothesis_probability_bps"},
        "genome",
    )
    hypothesis = _require_nonempty_string(
        raw_genome["hypothesis"], "genome.hypothesis"
    )
    if hypothesis not in VERSIONS:
        raise RequestError("genome.hypothesis must be one of: v1, v2, v3, v4")
    confidence = raw_genome["hypothesis_probability_bps"]
    if type(confidence) is not int:
        raise RequestError("genome.hypothesis_probability_bps must be an integer")
    if not MIN_CONFIDENCE_BPS <= confidence <= MAX_CONFIDENCE_BPS:
        raise RequestError(
            "genome.hypothesis_probability_bps must be between "
            f"{MIN_CONFIDENCE_BPS} and {MAX_CONFIDENCE_BPS}"
        )
    return {
        "hypothesis": hypothesis,
        "hypothesis_probability_bps": confidence,
    }


def _decode_probe(raw_probe: object) -> dict[str, str]:
    if type(raw_probe) is not dict:
        raise RequestError("probe must be a JSON object")
    operation = _require_nonempty_string(raw_probe.get("operation"), "probe.operation")
    if operation == "list":
        _require_exact_keys(raw_probe, {"operation"}, "probe")
        return {"operation": "list"}
    if operation == "read":
        _require_exact_keys(raw_probe, {"operation", "path"}, "probe")
        path = _require_nonempty_string(raw_probe["path"], "probe.path")
        if path not in PATHS:
            raise RequestError(
                "probe.path must be one of: config/mode.txt, service/port.txt"
            )
        return {"operation": "read", "path": path}
    raise RequestError("probe.operation must be one of: list, read")


def decode_request(
    source: str,
) -> tuple[str, dict[str, object], dict[str, str]]:
    request = _decode_json(source)
    _require_exact_keys(
        request,
        {"schema_version", "candidate_id", "genome", "probe"},
        "request",
    )
    if (
        type(request["schema_version"]) is not int
        or request["schema_version"] != SCHEMA_VERSION
    ):
        raise RequestError(f"schema_version must be {SCHEMA_VERSION}")
    candidate_id = _require_nonempty_string(
        request["candidate_id"], "candidate_id"
    )
    if CANDIDATE_ID_PATTERN.fullmatch(candidate_id) is None:
        raise RequestError("candidate_id must be a lowercase SHA-256 identifier")
    genome = _decode_genome(request["genome"])
    expected_id = digest(
        {
            "genome": genome,
            "genome_schema": "flat-json-atoms-v1",
            "schema_version": SCHEMA_VERSION,
        }
    )
    if candidate_id != expected_id:
        raise RequestError("candidate_id does not match the supplied genome")
    probe = _decode_probe(request["probe"])
    return candidate_id, genome, probe


def _result_for(version: str, probe: dict[str, str]) -> dict[str, object]:
    if probe["operation"] == "list":
        return {"kind": "listing", "paths": list(PATHS)}
    return {"kind": "text", "text": CONTENTS[version][probe["path"]]}


def _measurement(value: float) -> dict[str, object]:
    return {
        "base": 2.0,
        "infinite": False,
        "measure": "entropy",
        "value": value,
    }


def run_candidate(
    candidate_id: str,
    genome: dict[str, object],
    probe: dict[str, str],
) -> dict[str, object]:
    hypothesis = str(genome["hypothesis"])
    confidence = int(genome["hypothesis_probability_bps"]) / 10000.0
    other_probability = (1.0 - confidence) / (len(VERSIONS) - 1)
    version_probabilities = {
        version: confidence if version == hypothesis else other_probability
        for version in VERSIONS
    }

    grouped: dict[str, list[float]] = {}
    for version in VERSIONS:
        target = canonical_json(_result_for(version, probe))
        grouped.setdefault(target, []).append(version_probabilities[version])
    outcomes: list[dict[str, object]] = []
    for target in sorted(grouped):
        probability = math.fsum(grouped[target])
        outcomes.append(
            {
                "probability": 0.0 if probability == 0.0 else probability,
                "target": target,
            }
        )
    forecast_entropy = entropy(
        [float(outcome["probability"]) for outcome in outcomes],
        base=2,
    )
    return {
        "candidate_id": candidate_id,
        "forecast": {
            "entropy": _measurement(forecast_entropy),
            "outcomes": outcomes,
        },
        "genome": genome,
        "probe": probe,
        "runner_model": RUNNER_MODEL,
        "schema_version": SCHEMA_VERSION,
    }


def _error_document(code: str, message: str) -> dict[str, object]:
    return {"error": {"code": code, "message": message}}


def _write_document(stream: object, document: dict[str, object]) -> None:
    stream.write(canonical_json(document) + "\n")
    stream.flush()


def _write_error(code: str, message: str) -> None:
    _write_document(sys.stderr, _error_document(code, message))


def _read_stdin() -> str:
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        return sys.stdin.read()
    try:
        return stream.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RequestError("standard input must be valid UTF-8 JSON") from exc


def _process(source: str) -> dict[str, object]:
    candidate_id, genome, probe = decode_request(source)
    return run_candidate(candidate_id, genome, probe)


def _run_jsonl() -> int:
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
            _write_error("invalid_request", f"cannot read standard input: {exc}")
            return 2

        try:
            if invalid_utf8:
                raise RequestError("request line must be valid UTF-8 JSON")
            response = _process(source)
        except RequestError as exc:
            response = _error_document("invalid_request", str(exc))
        except ProbabilityError as exc:
            response = _error_document("invalid_probability", str(exc))
        _write_document(sys.stdout, response)
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ["--jsonl"]:
        return _run_jsonl()
    if arguments:
        _write_error("invalid_request", "command-line arguments are not supported")
        return 2
    try:
        response = _process(_read_stdin())
    except RequestError as exc:
        _write_error("invalid_request", str(exc))
        return 2
    except ProbabilityError as exc:
        _write_error("invalid_probability", str(exc))
        return 2
    _write_document(sys.stdout, response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
