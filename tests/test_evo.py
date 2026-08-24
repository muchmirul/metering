from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import evo
from evo import Candidate, Transition, Verdict, step


ROOT = Path(__file__).resolve().parents[1]


def test_step_promotes_the_challenger():
    parent = Candidate("parent", {"score": 1})
    evidence = {"delta": 1}

    transition = step(
        parent,
        lambda current: Candidate(
            "child",
            {"score": current.value["score"] + 1},
        ),
        lambda incumbent, challenger: Verdict(challenger.id, evidence),
    )

    assert transition.parent is parent
    assert transition.challenger.value == {"score": 2}
    assert transition.verdict.evidence is evidence
    assert transition.next_parent is transition.challenger


def test_step_can_retain_the_parent():
    parent = Candidate("stable", "v1")

    transition = step(
        parent,
        lambda _: Candidate("trial", "v2"),
        lambda incumbent, challenger: Verdict(
            incumbent.id,
            {"reason": "regression"},
        ),
    )

    assert transition.next_parent is parent


def test_candidate_values_and_evidence_are_domain_agnostic():
    parent = Candidate("policy-a", ("tool", "safe"))
    evidence = object()

    transition = step(
        parent,
        lambda _: Candidate("policy-b", ("tool", "fast")),
        lambda incumbent, challenger: Verdict(challenger.id, evidence),
    )

    assert transition.next_parent.value == ("tool", "fast")
    assert transition.verdict.evidence is evidence


def test_a_population_can_be_one_candidate_value():
    parent = Candidate("population-a", ["agent-1", "agent-2"])

    transition = step(
        parent,
        lambda current: Candidate(
            "population-b",
            [*current.value, "agent-3"],
        ),
        lambda incumbent, challenger: Verdict(
            challenger.id,
            {"survivors": 3},
        ),
    )

    assert transition.next_parent.value == ["agent-1", "agent-2", "agent-3"]


@pytest.mark.parametrize("value", ["", 1, None])
def test_candidate_requires_a_nonempty_string_id(value):
    with pytest.raises(ValueError, match="candidate id"):
        Candidate(value, "candidate")


@pytest.mark.parametrize("value", ["", 1, None])
def test_verdict_requires_a_nonempty_string_selected_id(value):
    with pytest.raises(ValueError, match="selected_id"):
        Verdict(value, None)


def test_transition_rejects_a_no_op_proposal():
    parent = Candidate("same", 1)

    with pytest.raises(ValueError, match="must differ"):
        Transition(parent, Candidate("same", 2), Verdict("same", None))


def test_transition_rejects_an_unknown_selection():
    with pytest.raises(ValueError, match="unknown candidate"):
        Transition(
            Candidate("parent", 1),
            Candidate("child", 2),
            Verdict("third", None),
        )


def test_step_rejects_invalid_callback_results():
    parent = Candidate("parent", 1)

    with pytest.raises(TypeError, match="parent"):
        step(
            1,
            lambda _: Candidate("child", 2),
            lambda incumbent, challenger: Verdict("child", None),
        )

    with pytest.raises(TypeError, match="propose"):
        step(
            parent,
            lambda _: 2,
            lambda incumbent, challenger: Verdict("parent", None),
        )

    with pytest.raises(TypeError, match="judge"):
        step(
            parent,
            lambda _: Candidate("child", 2),
            lambda incumbent, challenger: "child",
        )


def test_records_are_frozen():
    candidate = Candidate("candidate", 1)

    with pytest.raises(FrozenInstanceError):
        candidate.id = "changed"


def test_public_surface_is_exact_and_source_is_one_file():
    assert evo.__all__ == ["Candidate", "Transition", "Verdict", "step"]
    files = {
        path.name
        for path in (ROOT / "src" / "evo").iterdir()
        if path.is_file() and path.suffix == ".py"
    }
    assert files == {"__init__.py"}
