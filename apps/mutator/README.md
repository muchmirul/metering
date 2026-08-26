# Mutator

`mutator.py` supports two explicit variation boundaries. Schema version 1
generates exactly one legal one-locus child from an immutable flat genome and a
finite mutation model. Schema version 2 either binds one caller-proposed agent
artifact or invokes one strict proposer command, then binds immutable parent and
challenger content identities. Artifacts may be default, skill, or Git-backed
source/output descriptors.

It is a variation operator, not an evolutionary system:

```text
parent genome + catalogue + mutation distribution + draw
                            |
                            v
                         mutator
                            |
                            v
              one child and named measurements
```

The application does not evaluate behavior, select a winner, advance a lineage,
learn a mutation policy, or repeat generations. Its schema-v2 proposal form may
invoke exactly one caller-selected agent command, but receives no evaluator
results and makes no retention decision.

## Run

From the repository root:

```bash
printf '%s\n' \
  '{"schema_version":1,"catalogue":{"loci":[{"locus":"planner","alleles":["react-v1","plan-execute-v1","reflect-v1"]},{"locus":"max_steps","alleles":[4,8,12]}]},"parent_genome":{"planner":"react-v1","max_steps":8},"mutation_distribution":[{"locus":"planner","allele":"plan-execute-v1","probability":0.5},{"locus":"planner","allele":"reflect-v1","probability":0.25},{"locus":"max_steps","allele":12,"probability":0.25}],"draw":0.6}' \
  | uv run python apps/mutator/mutator.py
```

Use `--jsonl` to process multiple independent requests through one process. One
canonical response or error is flushed for each input line. No parent, child, or
policy state survives between lines.

## Contract

Version 1 deliberately uses a flat genome. Every locus has one JSON atom as its
allele: a non-empty string, a safe integer, a Boolean, or null. Floating-point,
array, and object alleles are excluded so candidate identity remains simple and
portable.

The catalogue defines legal alleles. The parent must contain exactly those
loci. Every mutation-distribution entry must change exactly one locus to a
different legal allele and must have positive probability. Metering validates
and measures the complete supplied distribution; the Mutator never normalizes,
smooths, or invents missing probability mass.

Catalogue loci, alleles, and mutation support are put into canonical order before
the draw is applied. Thus semantically equivalent input order produces the same
catalogue ID, selected mutation, child ID, and response.

The response contains:

- content IDs for the normalized catalogue, parent genome, and child genome;
- one transition ID for the selected parent-to-child mutation;
- the exact one-locus before and after values;
- Shannon entropy of the caller-declared mutation distribution; and
- self-information of the selected mutation.

Mutation entropy describes spread over possible changes. Mutation surprisal
describes how unlikely the selected change was under the declared policy.
Neither quantity establishes quality, usefulness, novelty, intelligence, or
expected improvement. The repository [Evolution Controller](../controller/README.md)
carries these content IDs into one fixed Candidate Runner evaluation.

## Agent and Git artifacts

Schema version 2 accepts `agent-default-v1`, normalized UTF-8 `agent-skill-v1`,
or immutable `git-candidate-v1`. The original form binds a challenger already
supplied by the caller. The proposal form sends only the current parent and
caller-approved context to one command, requires one complete replacement skill
or Git descriptor, and records the command identity as proposal provenance. A
Git descriptor binds source commit/tree/content identities and external output
digests; it does not embed source or model weights. In both forms Mutator reports
changed paths (`@git-candidate` for a changed Git descriptor) and never claims
that the challenger is better.

For a live tool-free skill proposal, use
`apps/mutator/pi_skill_proposer.py`. For a tool-enabled Git workspace proposal,
use [`../../artifacts/git/pi_git_proposer.py`](../../artifacts/git/README.md)
inside a reviewed builder sandbox. The bounded Evolution Driver provides the
complete request and persistence example in
[`../evolution_driver/README.md`](../evolution_driver/README.md).

Encode an existing local skill directory with:

```bash
uv run python apps/mutator/skill_artifact.py PATH
```

See the [agent-artifact evolution protocol](../../docs/agent-evolution.md) for the
artifact schema and complete six-application composition.

## Documentation

- [Architecture](docs/architecture.md)
- [Mathematical and biological foundations](docs/foundations.md)
- [Agent protocol](docs/agent-protocol.md)

## Files

```text
mutator/
    mutator.py
    pi_skill_proposer.py
    skill_artifact.py
    README.md
    docs/
        architecture.md
        foundations.md
        agent-protocol.md
```
