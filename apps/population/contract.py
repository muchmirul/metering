"""Public source-only contract owned by Population Archive.

Outer sequencers use this facade rather than importing Population's private
protocol, policy, state, or SQLite implementation details.
"""

from __future__ import annotations

from apps.population.population_policy import (
    decode_allocation_request,
    decode_archive_request,
    normalize_allocation_body,
    normalize_archive_body,
    normalize_draw,
)
from apps.population.population_protocol import (
    MAX_PROTOCOL_INTEGER,
    POPULATION_SCHEMA_VERSION,
    RESOURCE_NAMES,
    PopulationError,
    PopulationState,
    RequestError,
    decode_candidate_request,
    decode_experiment_request,
    decode_initialize_request,
    decode_recombination_request,
    decode_run_request,
    normalize_distribution,
    normalize_resources,
)
from apps.population.population_state import (
    append_validated_record,
    initialize,
    load_state,
    locked_state,
    verify_summary,
)

__all__ = [
    "MAX_PROTOCOL_INTEGER",
    "POPULATION_SCHEMA_VERSION",
    "RESOURCE_NAMES",
    "PopulationError",
    "PopulationState",
    "RequestError",
    "append_validated_record",
    "decode_allocation_request",
    "decode_archive_request",
    "decode_candidate_request",
    "decode_experiment_request",
    "decode_initialize_request",
    "decode_recombination_request",
    "decode_run_request",
    "initialize",
    "load_state",
    "locked_state",
    "normalize_allocation_body",
    "normalize_archive_body",
    "normalize_distribution",
    "normalize_draw",
    "normalize_resources",
    "verify_summary",
]
