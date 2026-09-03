"""Pure evaluator-backed stopping predicates for Population Driver."""

from __future__ import annotations

from typing import cast

from apps.population.contract import PopulationState
from apps.population_driver.population_driver_protocol import STOPPING_POLICY_TYPE


def archive_reaches_development_goal(
    config: dict[str, object], archive: dict[str, object]
) -> bool:
    """Return whether one feasible member passes every accumulated public case."""

    policy = config.get("stopping")
    if type(policy) is not dict or policy.get("type") != STOPPING_POLICY_TYPE:
        return False
    minimum_replicates = policy.get("minimum_replicates")
    if type(minimum_replicates) is not int:
        return False
    members = archive.get("members")
    if type(members) is not list:
        return False
    for raw_member in members:
        if (
            type(raw_member) is not dict
            or raw_member.get("survival_passed") is not True
        ):
            continue
        replicate_count = raw_member.get("replicate_count")
        if type(replicate_count) is not int or replicate_count < minimum_replicates:
            continue
        task = raw_member.get("task")
        if (
            type(task) is dict
            and type(task.get("case_count")) is int
            and task["case_count"] > 0
            and task.get("passed_count") == task["case_count"]
        ):
            return True
    return False


def state_reaches_development_goal(
    config: dict[str, object], state: PopulationState
) -> bool:
    """Evaluate the configured goal against the latest development archive."""

    if "stopping" not in config:
        return False
    population = cast(dict[str, object], config["population"])
    experiment_id = str(population["experiment_id"])
    archive_id = state.latest_archive_by_experiment.get(experiment_id)
    if archive_id is None:
        return False
    archive = state.archives.get(archive_id)
    return type(archive) is dict and archive_reaches_development_goal(config, archive)
