"""One pairwise evolution transition.

The caller owns candidate identity, proposal, evaluation, evidence, persistence,
repetition, and stopping. This module only connects one parent, one challenger,
and one verdict into an explicit inherited successor.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True, slots=True)
class Candidate(Generic[T]):
    """One identified candidate value."""

    id: str
    value: T

    def __post_init__(self) -> None:
        if type(self.id) is not str or not self.id:
            raise ValueError("candidate id must be a non-empty string")


@dataclass(frozen=True, slots=True)
class Verdict(Generic[E]):
    """A judge's selected identity and caller-owned evidence."""

    selected_id: str
    evidence: E

    def __post_init__(self) -> None:
        if type(self.selected_id) is not str or not self.selected_id:
            raise ValueError("selected_id must be a non-empty string")


@dataclass(frozen=True, slots=True)
class Transition(Generic[T, E]):
    """One parent-versus-challenger selection transition."""

    parent: Candidate[T]
    challenger: Candidate[T]
    verdict: Verdict[E]

    def __post_init__(self) -> None:
        if not isinstance(self.parent, Candidate):
            raise TypeError("parent must be Candidate")
        if not isinstance(self.challenger, Candidate):
            raise TypeError("challenger must be Candidate")
        if not isinstance(self.verdict, Verdict):
            raise TypeError("verdict must be Verdict")
        if self.parent.id == self.challenger.id:
            raise ValueError("parent and challenger ids must differ")
        if self.verdict.selected_id not in {
            self.parent.id,
            self.challenger.id,
        }:
            raise ValueError("verdict selected an unknown candidate")

    @property
    def next_parent(self) -> Candidate[T]:
        """Return the candidate selected for inheritance."""

        if self.verdict.selected_id == self.challenger.id:
            return self.challenger
        return self.parent


async def step(
    parent: Candidate[T],
    propose: Callable[[Candidate[T]], Awaitable[Candidate[T]]],
    judge: Callable[
        [Candidate[T], Candidate[T]],
        Awaitable[Verdict[E]],
    ],
) -> Transition[T, E]:
    """Propose one challenger, judge the pair, and return one transition."""

    if not isinstance(parent, Candidate):
        raise TypeError("parent must be Candidate")

    challenger = await propose(parent)
    if not isinstance(challenger, Candidate):
        raise TypeError("propose must return Candidate")
    if challenger.id == parent.id:
        raise ValueError("parent and challenger ids must differ")

    verdict = await judge(parent, challenger)
    if not isinstance(verdict, Verdict):
        raise TypeError("judge must return Verdict")

    return Transition(parent=parent, challenger=challenger, verdict=verdict)
