"""Rebuildable SQLite query index for canonical population ledgers."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import cast

from apps.agent_protocol import ProtocolError, require_exact_keys, require_sha256
from apps.stdio_connector import canonical_digest, canonical_json

from apps.population.population_protocol import (
    INDEX_NAME,
    POPULATION_SCHEMA_VERSION,
    RESOURCE_NAMES,
    PopulationError,
    PopulationState,
    RequestError,
    state_paths,
)

INDEX_SCHEMA_VERSION = 1
_TABLES = (
    "metadata",
    "records",
    "candidates",
    "lineage",
    "experiments",
    "runs",
    "run_metrics",
    "archive_events",
    "archive_members",
    "allocations",
)


_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE records (
    sequence INTEGER PRIMARY KEY,
    record_id TEXT NOT NULL UNIQUE,
    parent_record_id TEXT,
    kind TEXT NOT NULL,
    document_json TEXT NOT NULL
);
CREATE TABLE candidates (
    candidate_id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL UNIQUE REFERENCES records(record_id),
    artifact_schema TEXT NOT NULL,
    artifact_json TEXT NOT NULL
);
CREATE TABLE lineage (
    child_candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    parent_position INTEGER NOT NULL,
    parent_candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    PRIMARY KEY (child_candidate_id, parent_position),
    UNIQUE (child_candidate_id, parent_candidate_id)
);
CREATE TABLE experiments (
    experiment_id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL UNIQUE REFERENCES records(record_id),
    role TEXT NOT NULL,
    task_set_id TEXT NOT NULL,
    evaluator_id TEXT NOT NULL,
    runtime_id TEXT NOT NULL,
    specification_json TEXT NOT NULL
);
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL UNIQUE REFERENCES records(record_id),
    candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    replicate_id TEXT NOT NULL,
    seed_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    measurements_json TEXT NOT NULL,
    UNIQUE (candidate_id, experiment_id, replicate_id)
);
CREATE TABLE run_metrics (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    name TEXT NOT NULL,
    value REAL,
    infinite INTEGER NOT NULL CHECK (infinite IN (0, 1)),
    unit TEXT NOT NULL,
    PRIMARY KEY (run_id, name)
);
CREATE TABLE archive_events (
    record_id TEXT PRIMARY KEY REFERENCES records(record_id),
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    eligible_count INTEGER NOT NULL,
    evaluated_count INTEGER NOT NULL,
    policy_json TEXT NOT NULL,
    objectives_json TEXT NOT NULL,
    excluded_json TEXT NOT NULL
);
CREATE TABLE archive_members (
    archive_record_id TEXT NOT NULL REFERENCES archive_events(record_id),
    candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    position INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    PRIMARY KEY (archive_record_id, candidate_id),
    UNIQUE (archive_record_id, position)
);
CREATE TABLE allocations (
    record_id TEXT PRIMARY KEY REFERENCES records(record_id),
    archive_record_id TEXT NOT NULL REFERENCES archive_events(record_id),
    selected_candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    draw_numerator INTEGER NOT NULL,
    draw_denominator INTEGER NOT NULL,
    ordered_candidates_json TEXT NOT NULL,
    probability_json TEXT NOT NULL,
    policy TEXT NOT NULL
);
"""


def _connect(path: str | Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        source = Path(path).resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(source, uri=True)
        connection.execute("PRAGMA query_only = ON")
    else:
        connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _metric(
    connection: sqlite3.Connection,
    run_id: str,
    name: str,
    value: float | int | None,
    *,
    infinite: bool = False,
    unit: str,
) -> None:
    connection.execute(
        "INSERT INTO run_metrics(run_id,name,value,infinite,unit) VALUES(?,?,?,?,?)",
        (run_id, name, value, int(infinite), unit),
    )


def _populate(connection: sqlite3.Connection, state: PopulationState) -> None:
    connection.executescript(_SCHEMA)
    source_id = canonical_digest([record["record_id"] for record in state.records])
    metadata = {
        "final_evaluation_started": canonical_json(state.final_evaluation_started),
        "index_schema_version": str(INDEX_SCHEMA_VERSION),
        "ledger_head_record_id": state.head_id,
        "ledger_record_count": str(len(state.records)),
        "ledger_source_id": source_id,
        "population_id": str(state.records[0]["record_id"]),
    }
    connection.executemany(
        "INSERT INTO metadata(key,value) VALUES(?,?)", sorted(metadata.items())
    )

    for record in state.records:
        sequence = int(record["sequence"])
        connection.execute(
            "INSERT INTO records(sequence,record_id,parent_record_id,kind,document_json) "
            "VALUES(?,?,?,?,?)",
            (
                sequence,
                str(record["record_id"]),
                record.get("parent_record_id"),
                str(record["kind"]),
                canonical_json(record),
            ),
        )

    for candidate_id in sorted(state.candidates):
        candidate = state.candidates[candidate_id]
        artifact = cast(dict[str, object], candidate["artifact"])
        connection.execute(
            "INSERT INTO candidates(candidate_id,record_id,artifact_schema,artifact_json) "
            "VALUES(?,?,?,?)",
            (
                candidate_id,
                state.candidate_record_ids[candidate_id],
                str(artifact["artifact_schema"]),
                canonical_json(artifact),
            ),
        )

    # Insert lineage only after every candidate exists; content IDs do not imply
    # parent-before-child lexical ordering.
    for candidate_id in sorted(state.candidates):
        for position, parent in enumerate(state.candidate_parents[candidate_id]):
            connection.execute(
                "INSERT INTO lineage(child_candidate_id,parent_position,parent_candidate_id) "
                "VALUES(?,?,?)",
                (candidate_id, position, parent),
            )

    for experiment_id in sorted(state.experiments):
        experiment = state.experiments[experiment_id]
        connection.execute(
            "INSERT INTO experiments(experiment_id,record_id,role,task_set_id,evaluator_id,"
            "runtime_id,specification_json) VALUES(?,?,?,?,?,?,?)",
            (
                experiment_id,
                state.experiment_record_ids[experiment_id],
                str(experiment["role"]),
                str(experiment["task_set_id"]),
                str(experiment["evaluator_id"]),
                str(experiment["runtime_id"]),
                canonical_json(experiment),
            ),
        )

    for body in state.runs:
        run = cast(dict[str, object], body["run"])
        evidence = cast(dict[str, object], body["evidence"])
        measurements = cast(dict[str, object], body["measurements"])
        run_id = str(run["run_id"])
        connection.execute(
            "INSERT INTO runs(run_id,record_id,candidate_id,experiment_id,replicate_id,"
            "seed_json,evidence_json,measurements_json) VALUES(?,?,?,?,?,?,?,?)",
            (
                run_id,
                state.run_record_ids[run_id],
                str(run["candidate_id"]),
                str(run["experiment_id"]),
                str(run["replicate_id"]),
                canonical_json(run["seed"]),
                canonical_json(evidence),
                canonical_json(measurements),
            ),
        )
        _metric(
            connection,
            run_id,
            "task_rate",
            float(measurements["task_rate"]),
            unit="ratio",
        )
        _metric(
            connection,
            run_id,
            "survival_passed",
            int(bool(measurements["survival_passed"])),
            unit="boolean",
        )
        _metric(
            connection,
            run_id,
            "budget_passed",
            int(bool(measurements["budget_passed"])),
            unit="boolean",
        )
        loss = cast(dict[str, object], measurements["mean_target_surprisal_bits"])
        _metric(
            connection,
            run_id,
            "mean_target_surprisal",
            None if loss["infinite"] else float(loss["value"]),
            infinite=bool(loss["infinite"]),
            unit="bits",
        )
        information = measurements["information_value_bits"]
        if information is not None:
            _metric(
                connection,
                run_id,
                "information_value",
                float(information),
                unit="bits",
            )
        cost = cast(dict[str, int], evidence["cost"])
        for name in RESOURCE_NAMES:
            _metric(
                connection,
                run_id,
                f"cost.{name}",
                cost[name],
                unit=name,
            )

    for archive_id, archive in sorted(state.archives.items()):
        connection.execute(
            "INSERT INTO archive_events(record_id,experiment_id,eligible_count,"
            "evaluated_count,policy_json,objectives_json,excluded_json) VALUES(?,?,?,?,?,?,?)",
            (
                archive_id,
                str(archive["experiment_id"]),
                int(archive["eligible_count"]),
                int(archive["evaluated_count"]),
                canonical_json(archive["policy"]),
                canonical_json(archive["objectives"]),
                canonical_json(archive["excluded"]),
            ),
        )
        members = cast(list[dict[str, object]], archive["members"])
        for position, member in enumerate(members):
            connection.execute(
                "INSERT INTO archive_members(archive_record_id,candidate_id,position,metrics_json) "
                "VALUES(?,?,?,?)",
                (
                    archive_id,
                    str(member["candidate_id"]),
                    position,
                    canonical_json(member),
                ),
            )

    for record_id, body in state.allocations:
        request = cast(dict[str, object], body["request"])
        result = cast(dict[str, object], body["result"])
        draw = cast(dict[str, int], request["draw"])
        connection.execute(
            "INSERT INTO allocations(record_id,archive_record_id,selected_candidate_id,"
            "draw_numerator,draw_denominator,ordered_candidates_json,probability_json,policy) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                record_id,
                str(request["archive_record_id"]),
                str(result["selected_candidate_id"]),
                draw["numerator"],
                draw["denominator"],
                canonical_json(result["ordered_candidates"]),
                canonical_json(result["probability"]),
                str(result["policy"]),
            ),
        )
    connection.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION}")
    connection.commit()


def _schema_snapshot(connection: sqlite3.Connection) -> list[list[object]]:
    rows = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name,tbl_name"
    ).fetchall()
    return [list(row) for row in rows]


def _snapshot(connection: sqlite3.Connection) -> dict[str, list[list[object]]]:
    snapshot: dict[str, list[list[object]]] = {}
    for table in _TABLES:
        columns = [
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        ]
        if not columns:
            raise PopulationError(f"population index is missing table: {table}")
        order = ",".join(f'"{column}"' for column in columns)
        rows = connection.execute(
            f'SELECT {order} FROM "{table}" ORDER BY {order}'
        ).fetchall()
        snapshot[table] = [list(row) for row in rows]
    return snapshot


def rebuild_index(root: Path, state: PopulationState) -> dict[str, object]:
    _, index = state_paths(root)
    if index.is_symlink():
        raise PopulationError(f"population index may not be a symlink: {index}")
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{INDEX_NAME}.", dir=root)
        os.close(descriptor)
        temporary = Path(name)
        connection = _connect(temporary)
        try:
            _populate(connection, state)
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                raise PopulationError("rebuilt population index failed integrity_check")
        finally:
            connection.close()
        os.replace(temporary, index)
        temporary = None
    except (OSError, sqlite3.Error) as exc:
        raise PopulationError(f"cannot rebuild population index: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return {
        "index_path": str(index),
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "ledger_head_record_id": state.head_id,
        "record_count": len(state.records),
        "schema_version": POPULATION_SCHEMA_VERSION,
    }


def verify_index(root: Path, state: PopulationState) -> dict[str, object]:
    _, index = state_paths(root)
    if index.is_symlink():
        raise PopulationError(f"population index may not be a symlink: {index}")
    if not index.is_file():
        raise PopulationError(
            f"population index does not exist; rebuild it first: {index}"
        )
    actual: sqlite3.Connection | None = None
    expected: sqlite3.Connection | None = None
    try:
        actual = _connect(index, readonly=True)
        expected = _connect(":memory:")
        _populate(expected, state)
        integrity = actual.execute("PRAGMA integrity_check").fetchone()
        foreign_keys = actual.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != ("ok",) or foreign_keys:
            raise PopulationError("population index failed SQLite integrity checks")
        actual_version = actual.execute("PRAGMA user_version").fetchone()
        expected_version = expected.execute("PRAGMA user_version").fetchone()
        if (
            actual_version != expected_version
            or _schema_snapshot(actual) != _schema_snapshot(expected)
            or _snapshot(actual) != _snapshot(expected)
        ):
            raise PopulationError(
                "population index does not match canonical ledger rebuild"
            )
    except sqlite3.Error as exc:
        raise PopulationError(f"cannot verify population index: {exc}") from exc
    finally:
        if actual is not None:
            actual.close()
        if expected is not None:
            expected.close()
    return {
        "index_path": str(index),
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "ledger_head_record_id": state.head_id,
        "schema_version": POPULATION_SCHEMA_VERSION,
        "verified": True,
    }


def _query_request(value: dict[str, object]) -> tuple[str, str | None]:
    try:
        query_type = value.get("type")
        if query_type in {"summary", "candidates"}:
            require_exact_keys(value, {"schema_version", "type"}, "request")
            candidate_id = None
        elif query_type == "lineage":
            require_exact_keys(
                value, {"candidate_id", "schema_version", "type"}, "request"
            )
            candidate_id = require_sha256(value["candidate_id"], "request.candidate_id")
        elif query_type == "archive":
            require_exact_keys(
                value, {"archive_record_id", "schema_version", "type"}, "request"
            )
            candidate_id = (
                None
                if value["archive_record_id"] is None
                else require_sha256(
                    value["archive_record_id"], "request.archive_record_id"
                )
            )
        else:
            raise ProtocolError(
                "request.type must be summary, candidates, lineage, or archive"
            )
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != POPULATION_SCHEMA_VERSION
        ):
            raise ProtocolError(
                f"request.schema_version must be {POPULATION_SCHEMA_VERSION}"
            )
        return str(query_type), candidate_id
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc


def query_index(
    root: Path, state: PopulationState, request: dict[str, object]
) -> dict[str, object]:
    query_type, identifier = _query_request(request)
    verify_index(root, state)
    _, index = state_paths(root)
    connection: sqlite3.Connection | None = None
    try:
        connection = _connect(index, readonly=True)
        if query_type == "summary":
            counts = {
                "allocations": connection.execute(
                    "SELECT count(*) FROM allocations"
                ).fetchone()[0],
                "archives": connection.execute(
                    "SELECT count(*) FROM archive_events"
                ).fetchone()[0],
                "candidates": connection.execute(
                    "SELECT count(*) FROM candidates"
                ).fetchone()[0],
                "experiments": connection.execute(
                    "SELECT count(*) FROM experiments"
                ).fetchone()[0],
                "records": connection.execute(
                    "SELECT count(*) FROM records"
                ).fetchone()[0],
                "runs": connection.execute("SELECT count(*) FROM runs").fetchone()[0],
            }
            result: object = {
                "counts": counts,
                "final_evaluation_started": state.final_evaluation_started,
                "head_record_id": state.head_id,
                "population_id": state.records[0]["record_id"],
            }
        elif query_type == "candidates":
            rows = connection.execute(
                "SELECT candidate_id,artifact_schema FROM candidates ORDER BY candidate_id"
            ).fetchall()
            result = []
            for candidate_id, artifact_schema in rows:
                parents = [
                    parent[0]
                    for parent in connection.execute(
                        "SELECT parent_candidate_id FROM lineage "
                        "WHERE child_candidate_id=? ORDER BY parent_position",
                        (candidate_id,),
                    ).fetchall()
                ]
                result.append(
                    {
                        "artifact_schema": artifact_schema,
                        "candidate_id": candidate_id,
                        "parents": parents,
                    }
                )
        elif query_type == "lineage":
            assert identifier is not None
            exists = connection.execute(
                "SELECT 1 FROM candidates WHERE candidate_id=?", (identifier,)
            ).fetchone()
            if exists is None:
                raise PopulationError(f"unknown indexed candidate: {identifier}")
            parents = [
                row[0]
                for row in connection.execute(
                    "SELECT parent_candidate_id FROM lineage WHERE child_candidate_id=? "
                    "ORDER BY parent_position",
                    (identifier,),
                ).fetchall()
            ]
            children = [
                row[0]
                for row in connection.execute(
                    "SELECT child_candidate_id FROM lineage WHERE parent_candidate_id=? "
                    "ORDER BY child_candidate_id",
                    (identifier,),
                ).fetchall()
            ]
            result = {
                "candidate_id": identifier,
                "children": children,
                "parents": parents,
            }
        else:
            archive_id = identifier
            if archive_id is None:
                row = connection.execute(
                    "SELECT record_id FROM archive_events ORDER BY "
                    "(SELECT sequence FROM records WHERE records.record_id=archive_events.record_id) "
                    "DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    raise PopulationError("population index contains no archive event")
                archive_id = str(row[0])
            archive = connection.execute(
                "SELECT experiment_id,eligible_count,evaluated_count,policy_json,"
                "objectives_json,excluded_json FROM archive_events WHERE record_id=?",
                (archive_id,),
            ).fetchone()
            if archive is None:
                raise PopulationError(f"unknown indexed archive: {archive_id}")
            import json

            members = [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT metrics_json FROM archive_members WHERE archive_record_id=? "
                    "ORDER BY position",
                    (archive_id,),
                ).fetchall()
            ]
            result = {
                "archive_record_id": archive_id,
                "eligible_count": archive[1],
                "evaluated_count": archive[2],
                "excluded": json.loads(archive[5]),
                "experiment_id": archive[0],
                "members": members,
                "objectives": json.loads(archive[4]),
                "policy": json.loads(archive[3]),
            }
    except sqlite3.Error as exc:
        raise PopulationError(f"cannot query population index: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()
    return {
        "query": query_type,
        "result": result,
        "schema_version": POPULATION_SCHEMA_VERSION,
    }
