"""SQLite-backed logical state for deterministic source-only population search."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import cast

from agent_protocol import decode_candidate
from stdio_connector import canonical_digest, canonical_json

STORE_SCHEMA_VERSION = 1
EVENT_SCHEMA = "population-event-v1"
MANIFEST_SCHEMA = "variant-manifest-v1"
EVIDENCE_SCHEMA = "population-evidence-v1"
STATE_SCHEMA = "population-state-v1"


class PopulationStoreError(RuntimeError):
    """Raised when a population database violates its logical contract."""


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id TEXT PRIMARY KEY,
    candidate_json TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    operator TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS parentage (
    child_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    position INTEGER NOT NULL CHECK (position IN (0, 1)),
    parent_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    PRIMARY KEY (child_id, position),
    UNIQUE (child_id, parent_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS evaluations (
    evidence_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    law_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    descriptors_json TEXT NOT NULL,
    resources_json TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS pool (
    candidate_id TEXT PRIMARY KEY REFERENCES candidates(candidate_id),
    weight REAL NOT NULL CHECK (weight >= 0.0)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS events (
    sequence INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    parent_event_id TEXT,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def _json_object(text: str, location: str) -> dict[str, object]:
    value = json.loads(text)
    if type(value) is not dict:
        raise PopulationStoreError(f"{location} must contain one JSON object")
    return cast(dict[str, object], value)


class PopulationStore:
    """One-run population registry, evidence store, pool, and event ledger."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> PopulationStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def initialize(self, law: dict[str, object]) -> tuple[str, bool]:
        law_json = canonical_json(law)
        law_id = canonical_digest(
            {"law": law, "law_schema": "population-law-v1"}
        )
        with self.connection:
            self.connection.executescript(SCHEMA_SQL)
            existing = self._metadata_optional("schema_version")
            if existing is not None:
                if existing != str(STORE_SCHEMA_VERSION):
                    raise PopulationStoreError("unsupported population database schema")
                if self._metadata("law_json") != law_json:
                    raise PopulationStoreError(
                        "population database was initialized with a different run law"
                    )
                if self._metadata("law_id") != law_id:
                    raise PopulationStoreError("stored run-law identity is inconsistent")
                return law_id, False
            self._set_metadata("schema_version", str(STORE_SCHEMA_VERSION))
            self._set_metadata("law_json", law_json)
            self._set_metadata("law_id", law_id)
            self._set_metadata("head_event_id", "")
            self._append_event("initialize", {"law": law, "law_id": law_id})
        return law_id, True

    def require_initialized(self) -> None:
        try:
            version = self._metadata("schema_version")
        except sqlite3.OperationalError as exc:
            raise PopulationStoreError(
                "population database is not initialized"
            ) from exc
        if version != str(STORE_SCHEMA_VERSION):
            raise PopulationStoreError("unsupported population database schema")

    @property
    def law_id(self) -> str:
        self.require_initialized()
        return self._metadata("law_id")

    def register_candidate(
        self,
        *,
        candidate: dict[str, object],
        parents: list[str],
        generation: int,
        operator: str,
        manifest: dict[str, object],
    ) -> bool:
        self.require_initialized()
        normalized_candidate = decode_candidate(candidate)
        candidate_id = str(normalized_candidate["candidate_id"])
        if len(parents) > 2 or len(set(parents)) != len(parents):
            raise PopulationStoreError("parents must contain zero, one, or two unique IDs")
        if candidate_id in parents:
            raise PopulationStoreError("a candidate cannot be its own parent")
        parent_generations: list[int] = []
        for parent_id in parents:
            row = self.connection.execute(
                "SELECT generation FROM candidates WHERE candidate_id = ?",
                (parent_id,),
            ).fetchone()
            if row is None:
                raise PopulationStoreError(f"unknown parent candidate: {parent_id}")
            parent_generations.append(int(row["generation"]))
        expected_generation = 0 if not parents else max(parent_generations) + 1
        if generation != expected_generation:
            raise PopulationStoreError(
                f"generation must be {expected_generation} for the declared parents"
            )
        if not operator or "\x00" in operator:
            raise PopulationStoreError("operator must be a non-empty string")
        manifest_json = canonical_json(manifest)
        manifest_id = canonical_digest(
            {"manifest": manifest, "manifest_schema": MANIFEST_SCHEMA}
        )
        candidate_json = canonical_json(normalized_candidate)
        existing = self.connection.execute(
            "SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        if existing is not None:
            stored_parents = self.parents(candidate_id)
            expected = (
                candidate_json,
                manifest_id,
                manifest_json,
                generation,
                operator,
                parents,
            )
            actual = (
                str(existing["candidate_json"]),
                str(existing["manifest_id"]),
                str(existing["manifest_json"]),
                int(existing["generation"]),
                str(existing["operator"]),
                stored_parents,
            )
            if actual != expected:
                raise PopulationStoreError(
                    "candidate ID is already registered with different lineage data"
                )
            return False
        payload = {
            "candidate": normalized_candidate,
            "generation": generation,
            "manifest": manifest,
            "manifest_id": manifest_id,
            "operator": operator,
            "parents": parents,
        }
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO candidates(
                    candidate_id, candidate_json, manifest_id, manifest_json,
                    generation, operator
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    candidate_json,
                    manifest_id,
                    manifest_json,
                    generation,
                    operator,
                ),
            )
            for position, parent_id in enumerate(parents):
                self.connection.execute(
                    "INSERT INTO parentage(child_id, position, parent_id) VALUES (?, ?, ?)",
                    (candidate_id, position, parent_id),
                )
            self._append_event("register_candidate", payload)
        return True

    def record_evaluation(
        self,
        *,
        candidate_id: str,
        environment_id: str,
        metrics: dict[str, float],
        constraints: dict[str, bool],
        descriptors: dict[str, object],
        resources: dict[str, float],
    ) -> tuple[str, bool]:
        self.require_initialized()
        if not self.has_candidate(candidate_id):
            raise PopulationStoreError(f"unknown candidate: {candidate_id}")
        if not environment_id or "\x00" in environment_id:
            raise PopulationStoreError("environment_id must be a non-empty string")
        evidence = {
            "candidate_id": candidate_id,
            "constraints": constraints,
            "descriptors": descriptors,
            "environment_id": environment_id,
            "evidence_schema": EVIDENCE_SCHEMA,
            "law_id": self.law_id,
            "metrics": metrics,
            "resources": resources,
        }
        evidence_id = canonical_digest(evidence)
        existing = self.connection.execute(
            "SELECT * FROM evaluations WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        if existing is not None:
            if self._evaluation_from_row(existing) != {
                **evidence,
                "evidence_id": evidence_id,
            }:
                raise PopulationStoreError(
                    "evidence ID is already stored with different content"
                )
            return evidence_id, False
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO evaluations(
                    evidence_id, candidate_id, law_id, environment_id,
                    metrics_json, constraints_json, descriptors_json, resources_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    candidate_id,
                    self.law_id,
                    environment_id,
                    canonical_json(metrics),
                    canonical_json(constraints),
                    canonical_json(descriptors),
                    canonical_json(resources),
                ),
            )
            self._append_event(
                "record_evaluation", {**evidence, "evidence_id": evidence_id}
            )
        return evidence_id, True

    def set_pool(self, entries: list[tuple[str, float]], *, reason: object) -> None:
        self.require_initialized()
        if not entries:
            raise PopulationStoreError("active pool must not be empty")
        if len({candidate_id for candidate_id, _ in entries}) != len(entries):
            raise PopulationStoreError("active pool candidate IDs must be unique")
        total = math.fsum(weight for _, weight in entries)
        if abs(total - 1.0) > 1e-12:
            raise PopulationStoreError("active pool weights must sum to one")
        for candidate_id, weight in entries:
            if not self.has_candidate(candidate_id):
                raise PopulationStoreError(f"unknown pool candidate: {candidate_id}")
            if not math.isfinite(weight) or weight < 0.0:
                raise PopulationStoreError("active pool weights must be finite and non-negative")
        normalized_entries = sorted(entries)
        payload = {
            "pool": [
                {"candidate_id": candidate_id, "weight": weight}
                for candidate_id, weight in normalized_entries
            ],
            "reason": reason,
        }
        with self.connection:
            self.connection.execute("DELETE FROM pool")
            self.connection.executemany(
                "INSERT INTO pool(candidate_id, weight) VALUES (?, ?)",
                normalized_entries,
            )
            self._append_event("set_pool", payload)

    def has_candidate(self, candidate_id: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM candidates WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
            is not None
        )

    def parents(self, candidate_id: str) -> list[str]:
        rows = self.connection.execute(
            "SELECT parent_id FROM parentage WHERE child_id = ? ORDER BY position",
            (candidate_id,),
        ).fetchall()
        return [str(row["parent_id"]) for row in rows]

    def evaluation(self, evidence_id: str) -> dict[str, object]:
        self.require_initialized()
        row = self.connection.execute(
            "SELECT * FROM evaluations WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        if row is None:
            raise PopulationStoreError(f"unknown evidence: {evidence_id}")
        return self._evaluation_from_row(row)

    def pool(self) -> list[dict[str, object]]:
        self.require_initialized()
        rows = self.connection.execute(
            "SELECT candidate_id, weight FROM pool ORDER BY candidate_id"
        ).fetchall()
        return [
            {"candidate_id": str(row["candidate_id"]), "weight": float(row["weight"])}
            for row in rows
        ]

    def snapshot(self) -> dict[str, object]:
        self.require_initialized()
        candidate_rows = self.connection.execute(
            "SELECT * FROM candidates ORDER BY candidate_id"
        ).fetchall()
        candidates: list[dict[str, object]] = []
        for row in candidate_rows:
            candidates.append(
                {
                    "candidate": _json_object(
                        str(row["candidate_json"]), "stored candidate"
                    ),
                    "generation": int(row["generation"]),
                    "manifest": _json_object(
                        str(row["manifest_json"]), "stored manifest"
                    ),
                    "manifest_id": str(row["manifest_id"]),
                    "operator": str(row["operator"]),
                    "parents": self.parents(str(row["candidate_id"])),
                }
            )
        evaluation_rows = self.connection.execute(
            "SELECT * FROM evaluations ORDER BY evidence_id"
        ).fetchall()
        state = {
            "candidates": candidates,
            "evaluations": [
                self._evaluation_from_row(row) for row in evaluation_rows
            ],
            "head_event_id": self._metadata("head_event_id") or None,
            "law": _json_object(self._metadata("law_json"), "stored law"),
            "law_id": self._metadata("law_id"),
            "pool": self.pool(),
            "state_schema": STATE_SCHEMA,
        }
        return {**state, "state_id": canonical_digest(state)}

    def verify(self) -> dict[str, object]:
        self.require_initialized()
        integrity = str(self.connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise PopulationStoreError(f"SQLite integrity check failed: {integrity}")
        foreign = self.connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign:
            raise PopulationStoreError("population database contains broken references")
        law = _json_object(self._metadata("law_json"), "stored law")
        expected_law_id = canonical_digest(
            {"law": law, "law_schema": "population-law-v1"}
        )
        if expected_law_id != self._metadata("law_id"):
            raise PopulationStoreError("stored run-law identity is invalid")
        for row in self.connection.execute(
            "SELECT * FROM candidates ORDER BY candidate_id"
        ):
            candidate = decode_candidate(
                _json_object(str(row["candidate_json"]), "stored candidate")
            )
            if candidate["candidate_id"] != row["candidate_id"]:
                raise PopulationStoreError("stored candidate identity is invalid")
            manifest = _json_object(str(row["manifest_json"]), "stored manifest")
            manifest_id = canonical_digest(
                {"manifest": manifest, "manifest_schema": MANIFEST_SCHEMA}
            )
            if manifest_id != row["manifest_id"]:
                raise PopulationStoreError("stored manifest identity is invalid")
            parents = self.parents(str(row["candidate_id"]))
            parent_generations = [
                int(
                    self.connection.execute(
                        "SELECT generation FROM candidates WHERE candidate_id = ?",
                        (parent_id,),
                    ).fetchone()[0]
                )
                for parent_id in parents
            ]
            expected_generation = 0 if not parents else max(parent_generations) + 1
            if int(row["generation"]) != expected_generation:
                raise PopulationStoreError("stored candidate generation is invalid")
        for row in self.connection.execute(
            "SELECT * FROM evaluations ORDER BY evidence_id"
        ):
            evidence = self._evaluation_from_row(row)
            payload = {
                key: value for key, value in evidence.items() if key != "evidence_id"
            }
            if canonical_digest(payload) != evidence["evidence_id"]:
                raise PopulationStoreError("stored evaluation identity is invalid")
        pool = self.pool()
        if pool:
            total = math.fsum(float(item["weight"]) for item in pool)
            if abs(total - 1.0) > 1e-12:
                raise PopulationStoreError("stored pool weights do not sum to one")
        parent_event_id: str | None = None
        expected_sequence = 1
        registered_ids: set[str] = set()
        evaluated_ids: set[str] = set()
        last_pool: list[dict[str, object]] | None = None
        initialization_seen = False
        for row in self.connection.execute("SELECT * FROM events ORDER BY sequence"):
            if int(row["sequence"]) != expected_sequence:
                raise PopulationStoreError("event sequence is not contiguous")
            stored_parent = row["parent_event_id"]
            if stored_parent != parent_event_id:
                raise PopulationStoreError("event parent chain is invalid")
            payload = _json_object(str(row["payload_json"]), "stored event payload")
            kind = str(row["kind"])
            expected_event_id = canonical_digest(
                {
                    "event_schema": EVENT_SCHEMA,
                    "kind": kind,
                    "parent_event_id": parent_event_id,
                    "payload": payload,
                }
            )
            if expected_event_id != row["event_id"]:
                raise PopulationStoreError("stored event identity is invalid")
            if kind == "initialize":
                if initialization_seen or expected_sequence != 1:
                    raise PopulationStoreError("initialization event is misplaced")
                if payload != {"law": law, "law_id": self._metadata("law_id")}:
                    raise PopulationStoreError("initialization event does not match run law")
                initialization_seen = True
            elif kind == "register_candidate":
                candidate = decode_candidate(payload.get("candidate"), "event candidate")
                registered_ids.add(str(candidate["candidate_id"]))
            elif kind == "record_evaluation":
                evidence_id = payload.get("evidence_id")
                if type(evidence_id) is not str:
                    raise PopulationStoreError("evaluation event lacks evidence identity")
                evaluated_ids.add(evidence_id)
            elif kind == "set_pool":
                raw_pool = payload.get("pool")
                if type(raw_pool) is not list:
                    raise PopulationStoreError("pool event lacks a pool array")
                last_pool = cast(list[dict[str, object]], raw_pool)
            else:
                raise PopulationStoreError(f"unknown event kind: {kind}")
            parent_event_id = expected_event_id
            expected_sequence += 1
        if not initialization_seen:
            raise PopulationStoreError("event ledger lacks initialization")
        if (parent_event_id or "") != self._metadata("head_event_id"):
            raise PopulationStoreError("event head does not match the ledger")
        stored_candidate_ids = {
            str(row[0])
            for row in self.connection.execute("SELECT candidate_id FROM candidates")
        }
        if registered_ids != stored_candidate_ids:
            raise PopulationStoreError("candidate registry does not match event ledger")
        stored_evidence_ids = {
            str(row[0])
            for row in self.connection.execute("SELECT evidence_id FROM evaluations")
        }
        if evaluated_ids != stored_evidence_ids:
            raise PopulationStoreError("evaluation registry does not match event ledger")
        current_pool = self.pool()
        if current_pool != ([] if last_pool is None else last_pool):
            raise PopulationStoreError("active pool does not match its latest event")
        snapshot = self.snapshot()
        return {
            "candidate_count": len(cast(list[object], snapshot["candidates"])),
            "evaluation_count": len(cast(list[object], snapshot["evaluations"])),
            "event_count": expected_sequence - 1,
            "state_id": snapshot["state_id"],
            "valid": True,
        }

    def _evaluation_from_row(self, row: sqlite3.Row) -> dict[str, object]:
        return {
            "candidate_id": str(row["candidate_id"]),
            "constraints": _json_object(
                str(row["constraints_json"]), "stored constraints"
            ),
            "descriptors": _json_object(
                str(row["descriptors_json"]), "stored descriptors"
            ),
            "environment_id": str(row["environment_id"]),
            "evidence_id": str(row["evidence_id"]),
            "evidence_schema": EVIDENCE_SCHEMA,
            "law_id": str(row["law_id"]),
            "metrics": _json_object(str(row["metrics_json"]), "stored metrics"),
            "resources": _json_object(
                str(row["resources_json"]), "stored resources"
            ),
        }

    def _metadata_optional(self, key: str) -> str | None:
        try:
            row = self.connection.execute(
                "SELECT value FROM metadata WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        return None if row is None else str(row["value"])

    def _metadata(self, key: str) -> str:
        value = self._metadata_optional(key)
        if value is None:
            raise PopulationStoreError(f"population database is missing metadata: {key}")
        return value

    def _set_metadata(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            (key, value),
        )

    def _append_event(self, kind: str, payload: dict[str, object]) -> str:
        parent_event_id = self._metadata("head_event_id") or None
        event_id = canonical_digest(
            {
                "event_schema": EVENT_SCHEMA,
                "kind": kind,
                "parent_event_id": parent_event_id,
                "payload": payload,
            }
        )
        sequence = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events"
            ).fetchone()[0]
        )
        self.connection.execute(
            """
            INSERT INTO events(sequence, event_id, parent_event_id, kind, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sequence, event_id, parent_event_id, kind, canonical_json(payload)),
        )
        self._set_metadata("head_event_id", event_id)
        return event_id
