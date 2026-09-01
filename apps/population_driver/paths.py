"""Population Driver-owned paths into its nested Population state."""

from __future__ import annotations

from pathlib import Path

from apps.population.contract import PopulationError, PopulationState, load_state
from apps.population_driver.population_driver_protocol import PopulationDriverError

POPULATION_DIRECTORY = "population"


def population_root(state_root: Path) -> Path:
    return state_root / POPULATION_DIRECTORY


def load_population(state_root: Path) -> PopulationState:
    root = population_root(state_root)
    try:
        return load_state(root)
    except PopulationError as exc:
        raise PopulationDriverError(str(exc)) from exc
