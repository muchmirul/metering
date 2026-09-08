"""Frozen, bounded trace projections over existing evidence and Git files.

This module has no server lifecycle, database, evaluation, or artifact-write authority.
"""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path

from apps._support.wire import canonical_digest
from apps.coding_agent.candidate_view import ExperimentView, _object, _views
from apps.coding_agent.file_view import CandidateFiles
from apps.coding_agent.operator_view import OperatorViewError, _page, progress_view
from apps.coding_agent.trace_labels import branch_labels

MAX_NODES = 2048
VERSION = "agentvolve-trace-graph-v1"


class TraceSnapshot:
    def __init__(self, runs: Path, selector: str):
        self.root, sources = _views(runs, selector)
        if sum(len(source.candidates) for source in sources) > MAX_NODES:
            raise OperatorViewError("trace graph exceeds its 2048-candidate bound")
        self.sources = {source.kind: source for source in sources}
        self.files = {
            kind: CandidateFiles(source) for kind, source in self.sources.items()
        }
        self.nodes: dict[str, dict[str, dict]] = {}
        provenance = []
        self.experiments = []
        for source in sources:
            parents = {
                identity: source.node(identity)["parent_candidate_id"]
                for identity in source.candidates
            }
            labels = branch_labels(source.prefix, parents)
            self.nodes[source.kind] = {
                identity: {
                    **source.node(identity),
                    **labels[identity],
                    "registration_sequence": record.get("sequence"),
                    "evidence": source.evidence_summary(identity),
                }
                for identity, record in source.candidates.items()
            }
            provenance.append(
                {
                    "kind": source.kind,
                    "run_root": str(source.root),
                    "reused": source.reused,
                    "population_id": source.population[0]["record_id"]
                    if source.population
                    else None,
                    "population_head": source.population[-1]["record_id"]
                    if source.population
                    else None,
                    "driver_head": source.driver[-1]["record_id"]
                    if source.driver
                    else None,
                    "pending_id": source.pending.get("pending_id")
                    if source.pending
                    else None,
                    "public_details_sha256": source.freeze_details(),
                }
            )
            for record in source.population:
                if record.get("kind") == "experiment":
                    body = _object(record.get("body"))
                    specification = _object(body.get("experiment"))
                    self.experiments.append(
                        {
                            "kind": source.kind,
                            "experiment_id": body.get("experiment_id"),
                            **{
                                key: specification.get(key)
                                for key in (
                                    "role",
                                    "task_set_id",
                                    "evaluator_id",
                                    "runtime_id",
                                )
                            },
                        }
                    )
        self.provenance = provenance
        # Already-existing safe progress summary; no raw profile, prompt, or protected asset is returned.
        progress = progress_view(runs, selector, include_diff=False)
        self.task = progress.get("task")
        self.worker = {
            **_object(progress.get("worker")),
            "state": progress.get("state"),
            "stage": progress.get("stage"),
        }
        self.snapshot_id = canonical_digest(
            {
                "view_schema": VERSION,
                "root": str(self.root),
                "sources": provenance,
                "task": self.task,
                "worker": self.worker,
            }
        )

    def source(self, kind: str) -> ExperimentView:
        if kind not in self.sources:
            raise OperatorViewError("unknown source experiment")
        return self.sources[kind]

    def node(self, kind: str, identity: str) -> dict:
        self.source(kind)
        if identity not in self.nodes[kind]:
            raise OperatorViewError("unknown registered candidate identity")
        return self.nodes[kind][identity]

    def envelope(self, data: dict) -> dict:
        return {
            "view_schema": VERSION,
            "authority": "projection-only",
            "snapshot_id": self.snapshot_id,
            **data,
        }

    def graph(self) -> dict:
        archives = []
        for kind, source in self.sources.items():
            for record in source.archives:
                body = _object(record.get("body"))
                archives.append(
                    {
                        "kind": kind,
                        "record_id": record["record_id"],
                        "sequence": record.get("sequence"),
                        "members": [
                            item["candidate_id"] for item in body.get("members", [])
                        ],
                        "excluded": [
                            {
                                "candidate_id": item["candidate_id"],
                                "reason": item.get("reason"),
                            }
                            for item in body.get("excluded", [])
                        ],
                    }
                )
        return self.envelope(
            {
                "workflow_root": str(self.root),
                "task": self.task,
                "worker": self.worker,
                "sources": self.provenance,
                "experiments": self.experiments,
                "nodes": [
                    node for nodes in self.nodes.values() for node in nodes.values()
                ],
                "archives": archives,
                "warnings": [
                    warning
                    for source in self.sources.values()
                    for warning in source.warnings
                ],
                "verification": "Not offline-verified by this viewer. Snapshot IDs bind evidence heads and captured public projections, not experimental correctness.",
                "semantics": "Results belong to candidate snapshots, not individual files. Historical archive filters do not rewind current evaluation summaries.",
            }
        )

    def report(self, kind: str, identity: str, offset: int = 0) -> dict:
        node = self.node(kind, identity)
        source = self.source(kind)
        events = source.candidate_events(identity)
        return self.envelope(
            {
                "node": node,
                "events": events[offset : offset + 10],
                "total_items": len(events),
                **_page(offset, len(events), 10),
            }
        )

    def loops(self, kind: str) -> dict:
        return self.envelope({"items": self.source(kind).loop_rows()})

    def loop(self, kind: str, label: str, offset: int = 0) -> dict:
        source = self.source(kind)
        source.loop_rows()  # Validate unique ordinals before resolving a label.
        rows = [*source.rounds, *([source.pending] if source.pending else [])]
        row = next(
            (row for row in rows if f"{source.prefix}R{row.get('round')}" == label),
            None,
        )
        if row is None:
            raise OperatorViewError("unknown recorded loop")
        events = source.loop_events(row)
        return self.envelope(
            {
                "label": label,
                "events": events[offset : offset + 10],
                "total_items": len(events),
                **_page(offset, len(events), 10),
            }
        )

    def file_history(self, kind: str, path_id: str) -> dict:
        source = self.source(kind)
        files = self.files[kind]
        deadline = time.monotonic() + 20
        rows = []
        found = False
        for identity, node in self.nodes[kind].items():
            if time.monotonic() > deadline:
                raise OperatorViewError(
                    "file history exceeds its time bound; no partial history is claimed"
                )
            entry = files.inventory(identity).get(path_id)
            found |= entry is not None
            parent = node["parent_candidate_id"]
            previous = files.inventory(parent).get(path_id) if parent else None
            change = (
                "absent"
                if entry is None and previous is None
                else "added"
                if previous is None
                else "deleted"
                if entry is None
                else "unchanged"
                if (entry["blob"], entry["mode"])
                == (previous["blob"], previous["mode"])
                else "modified"
            )
            rows.append(
                {
                    "candidate_id": identity,
                    "display_label": node["display_label"],
                    "parent_candidate_id": parent,
                    "depth": node["depth"],
                    "branch_index": node["branch_index"],
                    "file": entry,
                    "change": change,
                }
            )
        if not found:
            raise OperatorViewError(
                "file path is absent from this source's registered snapshots"
            )
        return self.envelope(
            {
                "kind": source.kind,
                "path_id": path_id,
                "items": rows,
                "semantics": "Exact raw-path history. Rename inference never silently connects identities. Null file means absent, not an empty blob.",
            }
        )

    def csv(self) -> bytes:
        output = io.StringIO(newline="")
        cost_columns = sorted(
            {
                f"{phase}_cost.{key}"
                for nodes in self.nodes.values()
                for node in nodes.values()
                for phase in ("development", "final")
                for key in (node["evidence"][phase] or {}).get("cost", {})
            }
        )
        columns = [
            "snapshot_id",
            "kind",
            "source_run",
            "population_head",
            "driver_head",
            "label",
            "registration_alias",
            "candidate_id",
            "parent_candidate_id",
            "commit",
            "git_tree",
            "birth_round",
            "depth",
            "branch",
            "status",
            "archive_status",
            "development_replicates",
            "development_passed",
            "development_cases",
            "development_safety_failures",
            "final_passed",
            "final_cases",
            "final_safety_failures",
            *cost_columns,
        ]
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for kind, nodes in self.nodes.items():
            for node in nodes.values():
                development = node["evidence"]["development"] or {}
                final = node["evidence"]["final"] or {}
                source = next(
                    source for source in self.provenance if source["kind"] == kind
                )
                row = {
                    "snapshot_id": self.snapshot_id,
                    "kind": kind,
                    "source_run": node["run_root"],
                    "population_head": source["population_head"],
                    "driver_head": source["driver_head"],
                    "label": node["display_label"],
                    "registration_alias": node["label"],
                    **{
                        key: node.get(key)
                        for key in (
                            "candidate_id",
                            "parent_candidate_id",
                            "commit",
                            "git_tree",
                            "birth_round",
                            "depth",
                            "branch",
                            "status",
                            "archive_status",
                        )
                    },
                    "development_replicates": development.get("replicates"),
                    "development_passed": development.get("passed_cases"),
                    "development_cases": development.get("total_cases"),
                    "development_safety_failures": development.get("safety_failures"),
                    "final_passed": final.get("passed_cases"),
                    "final_cases": final.get("total_cases"),
                    "final_safety_failures": final.get("safety_failures"),
                    **{
                        f"{phase}_cost.{key}": value
                        for phase, evidence in (
                            ("development", development),
                            ("final", final),
                        )
                        for key, value in evidence.get("cost", {}).items()
                    },
                }
                # Spreadsheet-safe presentation. JSON retains exact string identities.
                writer.writerow(
                    {
                        key: "'" + value
                        if isinstance(value, str)
                        and value[:1] in {"=", "+", "-", "@", "\t", "\r", "\n"}
                        else value
                        for key, value in row.items()
                    }
                )
        return output.getvalue().encode("utf-8")
