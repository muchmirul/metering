"""Read-only candidate trees, per-candidate reports, and recorded loop steps.

Labels are experiment-local presentation aliases in Population registration order.
No evaluator, mutation, archive policy, protected profile, or SQLite index is run.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from apps._support.diagnostics import operator_excerpt
from apps._support.wire import canonical_digest, canonical_json, decode_json_object
from apps.coding_agent.operator_view import (
    HEX_ID,
    OperatorViewError,
    _field,
    _git_output,
    _integer,
    _page,
    _records,
    _safe_text,
    trace_sources,
)

PAGE_SIZE = 20
EVENT_PAGE_SIZE = 10
DIFF_PAGE_SIZE = 40
MAX_DIFF_BYTES = 32 * 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _object(value: object) -> dict:
    return value if type(value) is dict else {}


def _list(value: object) -> list:
    return value if type(value) is list else []


def _text(value: object, limit: int = 1000) -> str | None:
    return _safe_text(value, limit) if type(value) is str else None


def _safe_path(root: Path, relative: str) -> Path:
    path = root
    if root.is_symlink():
        raise OperatorViewError("candidate source must not be a symbolic link")
    for part in Path(relative).parts:
        if part in {"..", "/"}:
            raise OperatorViewError("unsafe candidate evidence path")
        path /= part
        if path.is_symlink():
            raise OperatorViewError(f"candidate evidence must not follow symlinks: {path}")
    return path


def _ledger(root: Path, relative: str) -> list[dict]:
    path = _safe_path(root, relative)
    return _records(path, relative) if path.exists() else []


def _small_document(root: Path, relative: str) -> dict | None:
    path = _safe_path(root, relative)
    if not path.exists():
        return None
    if not path.is_file():
        raise OperatorViewError(f"candidate report is not a regular file: {path}")
    try:
        with path.open("rb") as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise OperatorViewError(f"candidate report document exceeds its bound: {path}")
        source = raw.decode("ascii")
    except (OSError, UnicodeError) as exc:
        raise OperatorViewError(f"cannot read candidate report: {path}") from exc
    document = decode_json_object(source, OperatorViewError)
    if source != canonical_json(document) + "\n":
        raise OperatorViewError(f"candidate report is not canonical: {path}")
    return document


def _event(step: str, summary: str, reference: object = None, **data: object) -> dict:
    return {"step": step, "summary": summary, "record_id": _text(reference, 128), **data}


class ExperimentView:
    """A disposable in-memory index of one bounded pair of canonical ledgers."""

    def __init__(self, kind: str, root: Path, reused: bool):
        self.kind, self.root, self.reused = kind, root, reused
        self.prefix = "H" if kind == "harness" else "S"
        self.population = _ledger(root, "state/population/population.jsonl")
        self.driver = _ledger(root, "state/driver.jsonl")
        self.records = {record["record_id"]: record for record in self.population}
        self.roles = {
            _object(record.get("body")).get("experiment_id"): _field(_field(record, "body"), "experiment").get("role")
            for record in self.population
            if record.get("kind") == "experiment" and type(_field(_field(record, "body"), "experiment")) is dict
        }
        self.candidates: dict[str, dict] = {}
        self.labels: dict[str, str] = {}
        self.warnings: list[str] = []
        for record in self.population:
            if record.get("kind") != "candidate":
                continue
            body = _object(record.get("body"))
            candidate = _object(body.get("candidate"))
            identity = candidate.get("candidate_id")
            if type(identity) is not str or not SHA256.fullmatch(identity) or identity in self.candidates:
                raise OperatorViewError("candidate registration has an invalid or duplicate identity")
            parents = body.get("parents")
            if type(parents) is not list or len(parents) > 1 or any(type(parent) is not str or parent not in self.candidates for parent in parents):
                raise OperatorViewError("candidate ancestry must reference an earlier single parent")
            self.labels[identity] = f"{self.prefix}{len(self.candidates)}"
            self.candidates[identity] = record
        if not self.population:
            self.warnings.append(f"{kind}: Population ledger unavailable; no candidate nodes can be reconstructed.")
        self.rounds = [record for record in self.driver if record.get("kind") == "round"]
        self.pending = _small_document(root, "state/pending/round-intent.json")
        if self.pending and self.pending.get("pending_id") != canonical_digest({key: value for key, value in self.pending.items() if key != "pending_id"}):
            raise OperatorViewError("pending round intent has an invalid content identity")
        # A crash can leave a completed round and its old pending intent. Do not duplicate it.
        if self.pending and any(record.get("intent_id") == self.pending.get("intent_id") for record in self.rounds):
            self.pending = None
        self.archives = [record for record in self.population if record.get("kind") == "archive"
                         and self.roles.get(_field(record.get("body"), "experiment_id")) == "development"]
        self.final_runs = [record for record in self.population if record.get("kind") == "run"
                           and self.roles.get(_field(_field(record.get("body"), "run"), "experiment_id")) == "final"]
        final_candidates = {_field(_field(record.get("body"), "run"), "candidate_id") for record in self.final_runs}
        if len(self.final_runs) > 1 or any(identity not in self.candidates for identity in final_candidates):
            raise OperatorViewError("protected final records do not identify one registered candidate")
        self.selected = next(iter(final_candidates), None)
        self._diagnostics: dict[str, list[dict]] | None = None
        self._frozen_loops: dict[str, list[dict]] | None = None

    def label(self, identity: object) -> str:
        return self.labels.get(str(identity), "unavailable")

    def body(self, reference: object, kind: str) -> dict:
        if reference is None:
            return {}
        record = self.records.get(str(reference))
        if record is None or record.get("kind") != kind:
            raise OperatorViewError(f"loop references an unavailable {kind} record")
        return _object(record.get("body"))

    def archive_status(self, identity: str, archive: dict | None = None) -> tuple[str, str | None]:
        archive = archive or (self.archives[-1] if self.archives else {})
        body = _object(archive.get("body"))
        if any(_field(item, "candidate_id") == identity for item in _list(body.get("members"))):
            return "retained", None
        excluded = next((item for item in _list(body.get("excluded")) if _field(item, "candidate_id") == identity), None)
        if excluded is not None:
            return "eliminated", _text(excluded.get("reason"))
        return "not-yet-archived", None

    def node(self, identity: str) -> dict:
        record = self.candidates[identity]
        body = _object(record.get("body"))
        artifact = _object(_field(body.get("candidate"), "artifact"))
        parents = body["parents"]
        archive_status, reason = self.archive_status(identity)
        births = [row for row in self.rounds if row.get("child_candidate_id") == identity]
        return {
            "label": self.label(identity), "candidate_id": identity,
            "parent_label": self.label(parents[0]) if parents else None,
            "parent_candidate_id": parents[0] if parents else None,
            "kind": self.kind, "run_root": str(self.root), "reused": self.reused,
            "commit": _text(artifact.get("commit"), 128), "git_tree": _text(artifact.get("git_tree"), 128),
            "entrypoint": _text(artifact.get("entrypoint")), "record_id": record["record_id"],
            "birth_round": _integer(births[0].get("round")) if births else None,
            "status": "selected" if identity == self.selected else archive_status,
            "archive_status": archive_status, "exclusion_reason": reason,
        }

    def tree(self) -> list[dict]:
        children: dict[str | None, list[str]] = {}
        for identity, record in self.candidates.items():
            parents = _object(record["body"])["parents"]
            children.setdefault(parents[0] if parents else None, []).append(identity)
        output: list[dict] = []
        # Iterative DFS avoids recursion limits on long but valid single lineages.
        stack = [(identity, "", "", 0) for identity in reversed(children.get(None, []))]
        while stack:
            identity, prefix, branch, depth = stack.pop()
            output.append({**self.node(identity), "tree_prefix": prefix + branch, "depth": depth})
            descendants = children.get(identity, [])
            child_prefix = prefix + ("   " if branch == "└─ " else "│  " if branch else "")
            for index in range(len(descendants) - 1, -1, -1):
                stack.append((descendants[index], child_prefix, "└─ " if index == len(descendants) - 1 else "├─ ", depth + 1))
        return output

    def diagnostics(self) -> dict[str, list[dict]]:
        if self._diagnostics is not None:
            return self._diagnostics
        diagnostics: dict[str, list[dict]] = {}
        directory = _safe_path(self.root, "state/diagnostics")
        if not directory.exists():
            self._diagnostics = diagnostics
            return diagnostics
        paths = sorted(directory.iterdir())
        if len(paths) > 4096:
            raise OperatorViewError("diagnostic directory exceeds the operator-view bound")
        total_bytes = 0
        deadline = time.monotonic() + 10
        for path in paths:
            if path.suffix != ".json" or not SHA256.fullmatch(path.stem):
                continue
            total_bytes += path.lstat().st_size
            if total_bytes > 32 * 1024 * 1024 or time.monotonic() > deadline:
                raise OperatorViewError("diagnostic scan exceeds its byte/time bound")
            document = _small_document(self.root, f"state/diagnostics/{path.name}")
            if document is None:
                continue
            if hashlib.sha256((canonical_json(document) + "\n").encode("ascii")).hexdigest() != path.stem:
                raise OperatorViewError("diagnostic digest does not match its contents")
            if document.get("diagnostic_schema") != "population-driver-failure-v1" or document.get("authority") != "diagnostic-only":
                raise OperatorViewError("unexpected Controller diagnostic schema")
            diagnostics.setdefault(str(document.get("attempt_id")), []).append({
                "intent_id": document.get("intent_id"), "sha256": path.stem,
                "elapsed_milliseconds": _integer(document.get("elapsed_milliseconds")),
                "error": {key: operator_excerpt(str(value))[:1000] for key, value in _object(document.get("error")).items()
                          if key in {"kind", "summary", "returncode", "detail_excerpt", "stderr_excerpt"}},
                "authority": "diagnostic-only",
            })
        self._diagnostics = diagnostics
        return diagnostics

    def freeze_details(self) -> str:
        """Capture each loop's public details once; return their projection digest."""
        if self._frozen_loops is None:
            self.loop_rows()
            frozen = {}
            total_bytes = 0
            deadline = time.monotonic() + 20
            for row in [*self.rounds, *([self.pending] if self.pending else [])]:
                if time.monotonic() > deadline:
                    raise OperatorViewError("public loop snapshot exceeds its time bound")
                events = self.loop_events(row)
                total_bytes += len(canonical_json(events))
                if total_bytes > 32 * 1024 * 1024:
                    raise OperatorViewError("public loop snapshot exceeds its byte bound")
                frozen[f"{self.prefix}R{row['round']}"] = events
            self._frozen_loops = frozen
        return canonical_digest(self._frozen_loops)

    def loop_rows(self) -> list[dict]:
        rows = [*self.rounds, *([self.pending] if self.pending else [])]
        ordinals = [row.get("round") for row in rows]
        if any(type(value) is not int or value < 1 for value in ordinals) or len(set(ordinals)) != len(ordinals):
            raise OperatorViewError("loop ordinals must be unique positive integers")
        return [{
            "label": f"{self.prefix}R{row.get('round')}", "round": _integer(row.get("round")),
            "parent_label": self.label(row.get("parent_candidate_id")),
            "child_label": self.label(row.get("child_candidate_id")) if row.get("child_candidate_id") else None,
            "state": str(row.get("stage", "committed")), "attempts": len(_list(row.get("attempts"))),
            "kind": self.kind, "run_root": str(self.root), "reused": self.reused,
        } for row in rows]

    def controller_details(self, row: dict) -> list[dict]:
        """Expose only public outcomes and the labelled proposal explanation, never prompts."""
        reference = _object(row.get("controller_receipt"))
        name, digest = reference.get("name"), reference.get("sha256")
        if type(name) is not str or not re.fullmatch(r"[0-9a-f]{64}\.controller\.json", name) or not SHA256.fullmatch(str(digest)):
            return [_event("Controller details unavailable", "No safe recorded Controller receipt reference.")]
        try:
            document = _small_document(self.root, f"state/receipts/{name}")
            if document is None:
                raise OperatorViewError("referenced Controller receipt is missing")
            if hashlib.sha256((canonical_json(document) + "\n").encode("ascii")).hexdigest() != digest:
                raise OperatorViewError("Controller receipt digest does not match")
            if document.get("attempt_id") not in {attempt.get("attempt_id") for attempt in _list(row.get("attempts")) if type(attempt) is dict} or name != f"{document.get('attempt_id')}.controller.json":
                raise OperatorViewError("Controller receipt belongs to another attempt")
            result = _object(document.get("controller_result"))
            mutation = _object(result.get("mutation"))
            if (_field(mutation.get("child"), "candidate_id") != row.get("child_candidate_id") or
                    _field(mutation.get("parent"), "candidate_id") != row.get("parent_candidate_id")):
                raise OperatorViewError("Controller receipt belongs to another generation")
            details = _object(mutation.get("mutation"))
            events = [_event("proposal explanation (model-authored)", _text(details.get("reason"), 4000) or "No proposal explanation recorded.",
                             proposal_id=details.get("proposal_id"), receipt_sha256=digest)]
            for report_key, identity in (("incumbent_report", row.get("parent_candidate_id")), ("challenger_report", row.get("child_candidate_id"))):
                report = _object(result.get(report_key))
                if report.get("candidate") != identity:
                    raise OperatorViewError("Controller case report belongs to another candidate")
                for case in _list(report.get("cases")):
                    case = _object(case)
                    events.append(_event("development check", f"{self.label(identity)}: {_text(case.get('case_id'))}",
                                         passed=case.get("passed"), safety_passed=case.get("safety_passed"), outcome=_text(case.get("outcome")),
                                         evidence=case.get("evidence"), controller_receipt_sha256=digest))
            return events
        except OperatorViewError as exc:
            return [_event("Controller details unavailable", _safe_text(exc))]

    def loop_events(self, row: dict) -> list[dict]:
        number = row.get("round")
        label = f"{self.prefix}R{number}"
        if self._frozen_loops is not None:
            return self._frozen_loops[label]
        allocation = row.get("parent_allocation_record_id")
        allocated = self.body(allocation, "allocation")
        parent_record = self.candidates.get(str(row.get("parent_candidate_id")))
        seed = parent_record is not None and not _object(parent_record.get("body")).get("parents")
        events = [_event("parent allocation", f"{label}: parent {self.label(row.get('parent_candidate_id'))}", allocation,
                         allocation=allocated or {"source": "registered seed" if seed else "allocation record unavailable"})]
        attempts = _list(row.get("attempts"))
        for index, attempt in enumerate(attempts):
            attempt = _object(attempt)
            failures = [item for item in self.diagnostics().get(str(attempt.get("attempt_id")), []) if item["intent_id"] == row.get("intent_id")]
            completed = index == len(attempts) - 1 and type(row.get("controller_receipt")) is dict
            state = "receipt recorded" if completed else "failed (diagnostic-only)" if failures else "superseded by explicit retry" if index < len(attempts) - 1 else "pending / indeterminate"
            events.append(_event("proposal attempt", f"{label}: attempt {index + 1} · {state}",
                                 attempt_id=_text(attempt.get("attempt_id"), 128), retry=attempt.get("retry") is True,
                                 reason=_text(attempt.get("reason")), wall_reservation_seconds=_integer(attempt.get("wall_reservation_seconds")),
                                 diagnostics=failures, receipt=row.get("controller_receipt") if completed else None))
        refs = _object(row.get("population_record_ids"))
        if row.get("kind") != "round":
            events.append(_event("pending round", f"{label}: {row.get('stage', 'unknown')} · round not committed; no child association inferred",
                                 error=operator_excerpt(str(row["last_error"])) if row.get("last_error") else None,
                                 evidence_receipt=row.get("evidence_receipt")))
            return events
        child = row.get("child_candidate_id")
        if child not in self.candidates:
            raise OperatorViewError("committed loop child has no Population registration")
        events.append(_event("mutation / Git child", f"{label}: {self.label(row.get('parent_candidate_id'))} → {self.label(child)}",
                             self.candidates[child]["record_id"], child=self.node(child),
                             variation=_object(self.candidates[child].get("body")).get("variation")))
        for key in ("incumbent_run", "challenger_run"):
            body = self.body(refs.get(key), "run")
            if body:
                events.append(self.evaluation_event(body, refs.get(key), label))
        events.extend(self.controller_details(row))
        selection = _object(row.get("selection"))
        events.append(_event("pairwise Selection Gate", f"{label}: {_text(selection.get('decision'))} · {_text(selection.get('reason'))}", row.get("record_id"),
                             selected_label=self.label(selection.get("selected")), comparison=selection.get("comparison"), policy=selection.get("policy")))
        archive = self.body(refs.get("archive"), "archive")
        events.append(_event("Population archive", f"{label}: archive membership, distinct from pairwise selection", refs.get("archive"),
                             members=[self.label(_field(item, "candidate_id")) for item in _list(archive.get("members"))],
                             excluded=[{"label": self.label(_field(item, "candidate_id")), "reason": _text(_field(item, "reason"))} for item in _list(archive.get("excluded"))]))
        next_allocation = row.get("next_allocation_record_id")
        next_body = self.body(next_allocation, "allocation")
        events.append(_event("next parent allocation", f"{label}: " + (self.label(_field(next_body.get("result"), "selected_candidate_id")) if next_body else "no next allocation recorded"),
                             next_allocation, allocation=next_body or None))
        return events

    def evaluation_event(self, body: dict, reference: object, label: str = "") -> dict:
        run, evidence = _object(body.get("run")), _object(body.get("evidence"))
        role = self.roles.get(run.get("experiment_id"), "unknown")
        return _event("independent evaluation", f"{label} {self.label(run.get('candidate_id'))}: {role} evidence",
                      reference, candidate_label=self.label(run.get("candidate_id")), role=role,
                      replicate_id=_text(run.get("replicate_id")), task=evidence.get("task"), cost=evidence.get("cost"),
                      measurements=body.get("measurements"), receipt=evidence.get("evidence_receipt"))

    def candidate_events(self, identity: str) -> list[dict]:
        events = [_event("registration", f"{self.label(identity)}: immutable candidate registered", self.candidates[identity]["record_id"])]
        for row in [*self.rounds, *([self.pending] if self.pending else [])]:
            if identity in {row.get("child_candidate_id"), row.get("parent_candidate_id")}:
                events.extend(self.loop_events(row))
        # Include membership changes caused by other branches, not just this candidate's own loops.
        for record in self.archives:
            state, reason = self.archive_status(identity, record)
            if state != "not-yet-archived":
                linked_round = next((row.get("round") for row in self.rounds if _field(row.get("population_record_ids"), "archive") == record["record_id"]), None)
                events.append(_event("archive snapshot", f"{self.label(identity)}: {state}" + (f" · {reason}" if reason else ""), record["record_id"],
                                     after_loop=f"{self.prefix}R{linked_round}" if linked_round is not None else None,
                                     population_sequence=record.get("sequence")))
        for record in self.final_runs:
            if _field(_field(record.get("body"), "run"), "candidate_id") == identity:
                events.append(self.evaluation_event(_object(record["body"]), record["record_id"]))
        return events

    def evidence_summary(self, identity: str) -> dict:
        summaries: dict[str, dict] = {}
        for record in self.population:
            body = _object(record.get("body"))
            run, evidence = _object(body.get("run")), _object(body.get("evidence"))
            if record.get("kind") != "run" or run.get("candidate_id") != identity:
                continue
            role = self.roles.get(run.get("experiment_id"), "unknown")
            if role not in {"development", "final"}:
                raise OperatorViewError("candidate evaluation references an unknown experiment role")
            summary = summaries.setdefault(role, {"replicates": 0, "passed_cases": 0, "total_cases": 0, "safety_failures": 0, "cost": {}})
            summary["replicates"] += 1
            task = _object(evidence.get("task"))
            for source, dest in (("passed_count", "passed_cases"), ("case_count", "total_cases"), ("safety_failures", "safety_failures")):
                value = _integer(task.get(source))
                if value is None or value < 0:
                    raise OperatorViewError("candidate evaluation has invalid counts")
                summary[dest] += value
            for key, value in _object(evidence.get("cost")).items():
                if type(value) is not int or value < 0:
                    raise OperatorViewError("candidate evaluation has invalid resources")
                summary["cost"][key] = summary["cost"].get(key, 0) + value
        return {"development": summaries.get("development"), "final": summaries.get("final"),
                "final_status": "recorded" if "final" in summaries else "not evaluated — no protected-final record for this candidate",
                "semantics": "Cumulative recorded cases/resources across replicates, not a new fitness score or total search cost."}

    def diff(self, identity: str, offset: int) -> dict:
        node = self.node(identity)
        result: dict = {"available": False, "lines": [], "total_lines": 0, "warning": None,
                        "base_commit": None, "commit": node["commit"], **_page(offset, 0, DIFF_PAGE_SIZE)}
        if node["parent_candidate_id"] is None:
            result["warning"] = "Seed candidate: no parent-relative mutation diff."
            return result
        base = self.node(node["parent_candidate_id"])["commit"]
        result["base_commit"] = base
        if not all(type(value) is str and HEX_ID.fullmatch(value) for value in (base, node["commit"])):
            result["warning"] = "Immutable Git commit binding unavailable."
            return result
        try:
            repository = _safe_path(self.root, "candidate.git")
            raw = _git_output(repository, ["diff", "--no-ext-diff", "--no-textconv", "--binary", "--unified=3", base, node["commit"], "--"], max_output_bytes=MAX_DIFF_BYTES)
            # Split long source lines into display fragments instead of silently clipping them.
            lines = [fragment for line in raw.splitlines() for fragment in
                     ([_safe_text(line[start:start + 200], 201) for start in range(0, len(line), 200)] or [""])]
            return {**result, "available": True, "total_lines": len(lines), "lines": lines[offset:offset + DIFF_PAGE_SIZE],
                    **_page(offset, len(lines), DIFF_PAGE_SIZE)}
        except OperatorViewError as exc:
            result["warning"] = _safe_text(exc)
            return result


def _views(runs: Path, selector: str) -> tuple[Path, list[ExperimentView]]:
    root, sources = trace_sources(runs, selector)
    return root, [ExperimentView(*source) for source in sources]


def tree_view(runs: Path, selector: str, offset: int = 0, *, loops: bool = False) -> dict:
    root, views = _views(runs, selector)
    items = [item for view in views for item in (view.loop_rows() if loops else view.tree())]
    page = _page(offset, len(items), PAGE_SIZE)
    return {"view_schema": "agentvolve-tree-view-v1", "authority": "projection-only", "mode": "loops" if loops else "tree",
            "workflow_root": str(root), "items": items[offset:offset + PAGE_SIZE], "total_items": len(items), **page,
            "warnings": [warning for view in views for warning in view.warnings]}


def report_view(runs: Path, selector: str, label: str, offset: int = 0, diff_offset: int = 0, *, loop: bool = False) -> dict:
    pattern = r"[HS]R[1-9][0-9]*" if loop else r"[HS](?:0|[1-9][0-9]*)"
    if not re.fullmatch(pattern, label):
        raise OperatorViewError("invalid candidate/loop label")
    root, views = _views(runs, selector)
    view = next((view for view in views if view.prefix == label[0]), None)
    if view is None:
        raise OperatorViewError("selected experiment is unavailable")
    if loop:
        rows = [*view.rounds, *([view.pending] if view.pending else [])]
        row = next((row for row in rows if f"{view.prefix}R{row.get('round')}" == label), None)
        if row is None:
            raise OperatorViewError("selected loop is unavailable")
        node = next(item for item in view.loop_rows() if item["label"] == label)
        events = view.loop_events(row)
        evidence, diff = None, None
    else:
        identity = next((identity for identity, alias in view.labels.items() if alias == label), None)
        if identity is None:
            raise OperatorViewError("selected candidate is unavailable")
        node = view.node(identity)
        events = view.candidate_events(identity)
        evidence = view.evidence_summary(identity)
        diff = view.diff(identity, diff_offset)
    page = _page(offset, len(events), EVENT_PAGE_SIZE)
    return {"view_schema": "agentvolve-candidate-report-v1", "authority": "projection-only", "workflow_root": str(root),
            "mode": "loop" if loop else "candidate", "node": node, "evidence": evidence, "diff": diff,
            "events": events[offset:offset + EVENT_PAGE_SIZE], "total_events": len(events), **page,
            "warnings": view.warnings, "verification": "Read-only projection of records; run offline verification before relying on evidence."}


def inspect_view(arguments: list[str]) -> dict:
    action = arguments[0]
    if action in {"tree", "loops"} and len(arguments) in {3, 4}:
        return tree_view(Path(arguments[1]), arguments[2], int(arguments[3]) if len(arguments) == 4 else 0, loops=action == "loops")
    if action in {"candidate", "loop"} and 4 <= len(arguments) <= (6 if action == "candidate" else 5):
        return report_view(Path(arguments[1]), arguments[2], arguments[3], int(arguments[4]) if len(arguments) >= 5 else 0,
                           int(arguments[5]) if len(arguments) == 6 else 0, loop=action == "loop")
    raise OperatorViewError("usage: tree|loops RUNS RUN [OFFSET] | candidate RUNS RUN H0|S0 [EVENT_OFFSET] [DIFF_OFFSET] | loop RUNS RUN HR1|SR1 [EVENT_OFFSET]")
