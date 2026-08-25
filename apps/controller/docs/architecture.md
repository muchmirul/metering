# Evolution Controller architecture

## Purpose

The controller is the narrow orchestration boundary for one generation. It
makes the previously caller-owned data movement executable without moving any
policy into Metering.

```text
controller
  -> Mutator
  -> Candidate Runner(parent, probe)
  -> Candidate Runner(child, probe)
  -> Observer(observe probe)
  -> Forecast Assay(parent evidence)
  -> Forecast Assay(child evidence)
  -> Selection Gate
  -> next_parent
```

Every dependency is invoked as a subprocess through its documented public
standard-stream protocol.

## Owned state transition

The controller owns one transition:

```text
(parent genome, explicit mutation request, fixed evaluation)
    -> selected next-parent genome
```

It does not own a lineage. A caller must explicitly use `next_parent` in a later
request, either directly or through the separate bounded Evolution Driver.

## Ordering

Observer `state` advertises the probe catalogue without revealing the active
version. For each requested probe, the controller obtains both complete runner
forecasts before delivering the Observer `observe` action. The observed result
is then encoded as canonical JSON and used as the common Forecast Assay target.

This ordering prevents this implementation from accidentally asking either
runner after reveal. It does not prove timing outside the trusted process.

## Binding checks

The controller verifies these links:

```text
runner incumbent candidate_id == Mutator parent candidate_id
runner challenger candidate_id == Mutator child candidate_id
assay incumbent candidate       == Mutator parent candidate_id
assay challenger candidate      == Mutator child candidate_id
gate selected candidate         in {parent candidate_id, child candidate_id}
```

Candidate Runner additionally recomputes each candidate ID from the supplied
genome. Before reveal, the controller verifies a nonempty set of unique,
normalized forecast outcomes; after reveal, it verifies that the observed
target is present. Candidate Runner owns completeness for its fixed model. The
controller cannot prove completeness for an arbitrary outcome domain.
Selection Gate verifies report mathematics and evidence alignment.

## Observer completion

Requested probes must be unique and public. Identification must become complete
on the final requested probe. The controller maps the final unit belief to the
snapshot IDs published by the initial `state` response, calls `finish`, and
requires `correct:true` before assay and selection.

## Failure boundary

Malformed outer requests are `invalid_request`. A component rejection, process
timeout, malformed component response, incomplete identification, identity
mismatch, or composition failure is `controller_error`. No failed generation
returns a retention decision.

## Deliberately absent

There is no candidate-code sandbox, hidden random draw, concurrency,
persistence, lineage store, policy learning, mutation adaptation, budget
optimization, deployment, or autonomous stopping rule inside Controller. A
request runs one finite generation. Schema version 1 uses fixed component
timeouts; schema version 2 carries explicit runner, evaluator, and optional
proposer timeouts. `controller.py` dispatches fixture orchestration locally and
schema-version-2 orchestration through `agent_generation.py`; this internal split
does not change the public command.
