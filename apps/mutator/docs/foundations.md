# Mutator foundations

## Biological role

Evolution by natural selection requires variation, differential retention or
reproduction, and heritable relation between parent and offspring. The Mutator
implements only the variation operation and exact inheritance of every
unchanged locus.

The closest engineering analogy is directed evolution:

```text
generate variant -> assay variant -> retain or reject -> repeat
```

This application is only `generate variant`. It does not establish evolution by
itself.

## Mutation kernel

For parent candidate `c` and caller-owned mutation policy parameters `theta`, a
mutation generator may be described by a finite conditional distribution:

```text
Q_theta(c' | c)
```

The request supplies the positive support of this distribution explicitly. For
probabilities `q_1 ... q_k`, Metering reports:

```text
H(Q) = -sum_j q_j log2(q_j)
```

This is the Shannon entropy of the next-mutation distribution. It measures how
spread out the declared policy is over supported changes.

For the selected mutation `m` with declared probability `q_m`, Metering reports:

```text
I(m) = -log2(q_m)
```

This is the selected mutation's self-information or surprisal.

Neither equation contains an assay result. Consequently:

```text
high entropy does not imply productive exploration
high surprisal does not imply a valuable mutation
rare does not mean good
```

Quality can be determined only after the child is expressed in an environment
and evaluated under a separately declared criterion.

## One-locus restriction

Version 1 changes exactly one locus. This is a causal and maintenance boundary,
not a claim that biology mutates only one site. Single-locus children make the
transition inspectable, keep the finite support exact, and reduce immediate
credit-assignment ambiguity. Multi-locus mutation and recombination can be
added later as distinct protocols after one-locus evidence exists.

## Determinism and replay

The process uses no internal random generator. Given the same normalized
catalogue, parent, distribution, and draw, it must return byte-equivalent
canonical output on the same supported numerical platform.

This makes the mutation event replayable without pretending the event was
predictable before the caller chose the draw. The external controller may obtain
that draw from a seeded generator, a hardware source, or a deterministic search;
the Mutator does not care and does not claim ownership of the source.

## Falsifiable implementation claim

For every accepted version 1 request:

1. the child differs from the parent at exactly one catalogue locus;
2. the replacement is a legal non-parent allele;
3. every unchanged locus is inherited byte-for-byte in canonical JSON meaning;
4. the selected support interval contains the supplied draw;
5. the entropy and surprisal equal Metering's public results for the supplied
   probabilities; and
6. semantically reordered catalogue and support arrays produce the same output.

A counterexample to any item falsifies the implementation claim.

## Research lineage

- Claude Shannon, “A Mathematical Theory of Communication,” 1948, supplies the
  entropy and self-information definitions.
- R. C. Lewontin, “The Units of Selection,” 1970, states minimal conditions for
  evolution by natural selection.
- K. Chen and F. H. Arnold, 1993, demonstrates sequential mutation and screening
  in directed evolution.
- G. R. Price, “Selection and Covariance,” 1970, separates selection effects
  from transmission and variation effects.

These foundations motivate the responsibility split. They do not prove that a
particular software mutation catalogue will produce useful agents.
