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

It does not own a lineage. A caller must explicitly use `next_parent.genome` in
a later request.

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
genome. The controller verifies that every complete forecast is normalized and
contains the revealed target. Selection Gate verifies report mathematics and
evidence alignment.

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

There is no candidate-code sandbox, arbitrary model adapter, hidden random draw,
concurrency, persistence, lineage store, policy learning, mutation adaptation,
budget optimization, deployment, or autonomous stopping rule. A request runs
one finite generation with a fixed ten-second timeout for each component
exchange.
