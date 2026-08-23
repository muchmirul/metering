# Architecture

## Purpose

Folder observer is a minimal controller between an external agent, a versioned
sandbox, and Metering. Its job is not to implement an agent. Its job is to make
one observation transition explicit and measurable.

The complete intended loop is:

```text
agent chooses one probe
        |
        v
controller predicts the probe's result distribution
        |
        +----> Metering measures the declared distribution
        |
        v
controller applies the probe to the active sandbox
        |
        v
controller conditions its belief on the result
        |
        v
agent receives the result, named measurements, and new belief
```

## Irreducible responsibilities

Each responsibility exists for one concrete reason:

1. **Versioned environment:** defines the possible sandbox states.
2. **Observation catalogue:** defines the operations the agent may request.
3. **Belief:** assigns explicit probability to every candidate version.
4. **Controller:** owns the active version and performs state transitions.
5. **Metering:** validates and measures caller-constructed distributions.
6. **Agent boundary:** accepts one action and returns one response.

Removing the environment leaves nothing to observe. Removing the catalogue
leaves no allowed action. Removing the belief leaves no probability model.
Removing the controller exposes private state or leaves updates undefined.
Removing Metering leaves the quantities unmeasured. Removing the agent boundary
returns to an application that chooses its own actions.

## Session state

The minimal target state is:

```text
active_version_id     controller-private truth
belief                version_id -> probability
catalogue_id          immutable observation definitions
step                  number of delivered observations
```

The active version never appears in an agent response before completion. The
belief, allowed probes, measurement inputs, measurement outputs, and delivered
observation are public.

The initial example uses a uniform belief, but uniformity is configuration, not
an architectural assumption:

```json
{"v1":0.25,"v2":0.25,"v3":0.25,"v4":0.25}
```

## Probability construction

For belief `B`, probe `q`, and possible result `r`, the controller constructs:

```text
P(result = r) = sum B(version)
                over versions where observe(version, q) = r
```

After the active sandbox produces `r`, deterministic conditioning is:

```text
B'(version) = B(version) / P(r)  when observe(version, q) = r
              0                  otherwise
```

The controller constructs and updates these distributions. Metering does not.
Metering may be asked for:

- entropy of the predicted result distribution;
- self-information of the delivered result; and
- entropy of the belief before or after conditioning.

These remain separately named quantities. The application does not emit an
overall score or generic information-gain value.

## Version identity

Content identity and history identity remain separate:

```text
tree_id     = SHA-256(canonical paths, sizes, and content hashes)
snapshot_id = SHA-256(parent_snapshot_id, tree_id)
```

`tree_id` identifies the measured folder contents. `snapshot_id` identifies
those contents at one place in the version lineage. The hashes detect changes
and accidental mixing; they are not authentication.

The agent-facing target gives the observation catalogue its own immutable
`catalogue_id`. If an agent or maintainer changes the available observations,
that creates a new catalogue version for a later session. A running session
never rewrites the meaning of an earlier observation.

## Dependency direction

```text
external agent -> folder observer -> public Metering JSON CLI
                       |
                       +----------> fixture sandbox
```

With `--history`, the measurement edge is explicit but one step longer:

```text
folder observer -> metering-history -> public Metering JSON CLI
                         |
                         +----------> caller-owned pair ledger
```

Metering knows nothing about folders, versions, probes, beliefs, agents, or
session state. Folder observer does not import private Metering modules. The
agent does not receive direct access to the active fixture directory.

The pair ledger is not the versioned environment. A folder `snapshot_id` binds
folder content to its parent snapshot; a measurement `record_id` binds one exact
Metering request/response pair to its parent record. Neither identifier implies
the other.

## Non-goals

The fundamental version does not require MCP, HTTP, plugins, a database,
persistent sessions, asynchronous execution, a generic tool framework, a model
adapter, or self-modifying observations.
