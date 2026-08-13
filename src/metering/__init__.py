"""Metering: replayable measurement for a controlled hidden-fault world.

The package is assembled from focused modules with one responsibility each, and
they are listed here in the order a run passes through them.

``schema`` holds the artifact vocabulary and the strict decoding rules that
every other module reuses.  ``events`` defines the typed actions, observations,
and trace events.  ``hidden_fault`` defines the world and the truth-free public
instance a policy is allowed to see.  ``policies`` is the harness boundary.
``runner`` owns the action loop and writes the artifacts.  ``trace`` provides
canonical encoding and append-only JSONL.  ``binding`` commits to the private
truth before the run.  ``replay`` rebuilds a finished run from its files, and
``report`` measures what it rebuilt.  ``calibration`` runs the whole instrument
against answers that are already known.
"""

from .binding import BindingError, compute_reference_commitment
from .calibration import (
    CalibrationFailure,
    CalibrationResult,
    run_calibration,
)
from .events import (
    Action,
    Diagnose,
    DiagnosticObservation,
    Event,
    EventError,
    Finish,
    FinishObservation,
    Observation,
    RawActionCost,
    Repair,
    RepairObservation,
    VerificationObservation,
    Verify,
    action_from_dict,
    action_to_dict,
    observation_from_dict,
    observation_to_dict,
)
from .hidden_fault import (
    ActionValidation,
    DiagnosticTest,
    HiddenFaultError,
    HiddenFaultSpec,
    HiddenFaultWorld,
    InvalidActionError,
    PublicInstance,
)
from .policies import (
    BalancedSearchPolicy,
    HarnessPolicy,
    PolicyError,
    SeededRandomSearchPolicy,
    SequentialSearchPolicy,
    remaining_candidates,
)
from .provenance import (
    CONTROLLER_VERSION,
    METER_VERSION,
    PACKAGE_VERSION,
    VERIFIER_VERSION,
)
from .replay import ReplayState, replay_trace
from .report import (
    ReportError,
    aggregate_reports,
    build_report,
    regenerate_report,
)
from .runner import (
    DEFAULT_ACTION_BUDGET,
    Controller,
    ControllerOutcome,
    RunResult,
    RunnerError,
    run_experiment,
    run_hidden_fault,
)
from .schema import (
    EVENT_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION,
    TERMINATION_BUDGET_EXHAUSTED,
    TERMINATION_HARNESS_CRASH,
    TERMINATION_INVALID_ACTION,
    TERMINATION_NORMAL,
    SchemaError,
)
from .trace import (
    RunPaths,
    TraceError,
    TraceReader,
    TraceWriter,
    canonical_json,
    read_events,
    read_json,
)

__version__ = PACKAGE_VERSION

__all__ = [
    "Action",
    "ActionValidation",
    "BalancedSearchPolicy",
    "BindingError",
    "CONTROLLER_VERSION",
    "CalibrationFailure",
    "CalibrationResult",
    "Controller",
    "ControllerOutcome",
    "DEFAULT_ACTION_BUDGET",
    "Diagnose",
    "DiagnosticObservation",
    "DiagnosticTest",
    "EVENT_SCHEMA_VERSION",
    "Event",
    "EventError",
    "Finish",
    "FinishObservation",
    "HarnessPolicy",
    "HiddenFaultError",
    "HiddenFaultSpec",
    "HiddenFaultWorld",
    "InvalidActionError",
    "MANIFEST_SCHEMA_VERSION",
    "METER_VERSION",
    "Observation",
    "PACKAGE_VERSION",
    "PolicyError",
    "PublicInstance",
    "REPORT_SCHEMA_VERSION",
    "RawActionCost",
    "Repair",
    "RepairObservation",
    "ReplayState",
    "ReportError",
    "RunPaths",
    "RunResult",
    "RunnerError",
    "SchemaError",
    "SeededRandomSearchPolicy",
    "SequentialSearchPolicy",
    "TERMINATION_BUDGET_EXHAUSTED",
    "TERMINATION_HARNESS_CRASH",
    "TERMINATION_INVALID_ACTION",
    "TERMINATION_NORMAL",
    "TraceError",
    "TraceReader",
    "TraceWriter",
    "VERIFIER_VERSION",
    "VerificationObservation",
    "Verify",
    "action_from_dict",
    "action_to_dict",
    "aggregate_reports",
    "build_report",
    "canonical_json",
    "compute_reference_commitment",
    "observation_from_dict",
    "observation_to_dict",
    "read_events",
    "read_json",
    "regenerate_report",
    "remaining_candidates",
    "replay_trace",
    "run_calibration",
    "run_experiment",
    "run_hidden_fault",
]
