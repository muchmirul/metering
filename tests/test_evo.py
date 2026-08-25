from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import evo
from evo import Candidate, Transition, Verdict, step


ROOT = Path(__file__).resolve().parents[1]


def run(awaitable):
    return asyncio.run(awaitable)


def test_step_promotes_the_challenger():
    parent = Candidate("parent", {"score": 1})
    evidence = {"delta": 1}

    async def propose(current):
        return Candidate("child", {"score": current.value["score"] + 1})

    async def judge(incumbent, challenger):
        return Verdict(challenger.id, evidence)

    transition = run(step(parent, propose, judge))

    assert transition.parent is parent
    assert transition.challenger.value == {"score": 2}
    assert transition.verdict.evidence is evidence
    assert transition.next_parent is transition.challenger


def test_step_can_retain_the_parent():
    parent = Candidate("stable", "v1")

    async def propose(_):
        return Candidate("trial", "v2")

    async def judge(incumbent, challenger):
        return Verdict(incumbent.id, {"reason": "regression"})

    transition = run(step(parent, propose, judge))

    assert transition.next_parent is parent


def test_population_and_evidence_types_are_caller_owned():
    parent = Candidate("population-a", ["agent-1", "agent-2"])
    evidence = object()

    async def propose(current):
        return Candidate("population-b", [*current.value, "agent-3"])

    async def judge(incumbent, challenger):
        return Verdict(challenger.id, evidence)

    transition = run(step(parent, propose, judge))

    assert transition.next_parent.value == ["agent-1", "agent-2", "agent-3"]
    assert transition.verdict.evidence is evidence


@pytest.mark.parametrize("value", ["", 1, None])
def test_candidate_requires_a_nonempty_string_id(value):
    with pytest.raises(ValueError, match="candidate id"):
        Candidate(value, "candidate")


@pytest.mark.parametrize("value", ["", 1, None])
def test_verdict_requires_a_nonempty_string_selected_id(value):
    with pytest.raises(ValueError, match="selected_id"):
        Verdict(value, None)


def test_transition_rejects_no_op_and_unknown_selection():
    parent = Candidate("same", 1)
    with pytest.raises(ValueError, match="must differ"):
        Transition(parent, Candidate("same", 2), Verdict("same", None))

    with pytest.raises(ValueError, match="unknown candidate"):
        Transition(
            Candidate("parent", 1),
            Candidate("child", 2),
            Verdict("third", None),
        )


def test_step_rejects_invalid_callback_results():
    parent = Candidate("parent", 1)

    async def valid_propose(_):
        return Candidate("child", 2)

    async def valid_judge(incumbent, challenger):
        return Verdict(challenger.id, None)

    async def bad_propose(_):
        return 2

    async def bad_judge(incumbent, challenger):
        return "child"

    with pytest.raises(TypeError, match="parent"):
        run(step(1, valid_propose, valid_judge))
    with pytest.raises(TypeError, match="propose"):
        run(step(parent, bad_propose, valid_judge))
    with pytest.raises(TypeError, match="judge"):
        run(step(parent, valid_propose, bad_judge))


def test_records_are_frozen():
    candidate = Candidate("candidate", 1)
    with pytest.raises(FrozenInstanceError):
        candidate.id = "changed"


def test_public_surface_and_core_size_are_intentionally_small():
    assert evo.__all__ == ["Candidate", "Transition", "Verdict", "step"]
    core = ROOT / "src" / "evo" / "core.py"
    assert len(core.read_text().splitlines()) < 120
