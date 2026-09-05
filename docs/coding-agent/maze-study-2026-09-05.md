# Agentvolve + Qwen3.8 maze study

Date: 2026-09-05 UTC. Application commit tested: `f76684d` (`Refactor Agentvolve experiment ownership`). The study did not modify application source or the original maze seed repositories.

> Publication note: this is the repository copy of the study report. The raw
> evidence, scripts, configurations, and generated runs remain in the operator's
> local archive at
> `/mnt/Tforce/dev/metering-maze-study-20260905.G6v0qS/` and are **not included in
> this repository**. Unless a repository path is explicitly named, artifact
> paths below refer to that archive. The published narrative and hashes alone
> are not a portable replay bundle.

## Verdict

**Level-1 solution evolution worked on the corrected maze benchmark. Additional generations did not improve measured correctness. Fresh Level-2 harness evolution did not complete in the attempted run.**

- All **six correctly configured solution runs** completed their prescribed generations, published selected commits and patches, passed offline verification, and passed independent output checks.
- Each selected program passed **4/4 public examples and 96/96 protected examples**. Its published patch applies to the unchanged seed.
- One-round and three-round Agentvolve tied on every maze family. Three rounds used **2.30× the recorded mutation tokens and 1.92× the measured workflow wall time**, in aggregate, with no additional correct answers.
- The fresh two-round harness attempt stopped during its second Controller attempt. The maze results therefore use the **predeclared previously verified harness**, not a newly evolved harness. They are not evidence of successful fresh end-to-end Level-2 → Level-1 operation.
- An initial six-treatment batch had a benchmark-authoring error, detailed below. It is preserved, not silently counted as success or as a maze-solving failure.

This is a small empirical pilot, not evidence that evolutionary search beats ordinary Pi, best-of-N sampling, or an equal-compute coding baseline.

## 1. Actual execution stack

These were live local-model runs, not fixture-generated candidates.

| Component | Observed configuration |
|---|---|
| Main model | `Qwen3.8-27B-Q4_K_M.gguf`, 26,895,998,464 parameters reported by the endpoint |
| MTP draft | `mtp-Qwen3.8-27B-Q4_0.gguf`, `draft-mtp` speculation |
| Backend | llama.cpp `0.1.0-dev`, build 755, commit `adb55e5`; alias `local` at `127.0.0.1:8080` |
| Acceleration | ROCm 7.2.1 libraries loaded, `--n-gpu-layers all`; AMD PCI device `1002:7551`, approximately 32 GiB VRAM; 100% GPU busy observed during inference |
| Pi | Reviewed **0.84.4**, using the existing matching installation; global 0.85.0 was not changed |
| Model contract | `pi-v1` / `llamacpp` / `local`, reasoning `medium`; 300-second model-call timeout, 64-call bound |
| Candidate execution | Reviewed digest-pinned Docker image; cgroup-v2; independent `KernelSession`s |
| Kernel limits | 512 MiB memory, 64 PIDs, 30-second kernel wall limit; individual test commands bounded at 10 seconds |

Image: `localhost:5000/metering-harness-runtime@sha256:35ca24b50d3d279f5f3e6d651e88036c7629f1426e481ead9eae20bc45aa3084`.

Main-model SHA-256: `31629f53165ab6a7dad8c9847dcfd1fdf55829dac1e6e748f4a68581b0033d34`.

Draft SHA-256: `051a1764cff8c4f3ee6ae8b00593a0364c7539c67fa50ffc58f3f96509fca38e`.

The model files, launcher binary, and model launch arguments matched the preflight observations after the searches finished. Server sampler defaults were temperature 1.0, top-k 20, top-p approximately 0.95, min-p approximately 0.05, and no fixed sampling seed. These are observed defaults, not a complete per-request sampling attestation.

See `preflight.json`, `postflight.json`, `hardware.json`, `server-props.json`, and `runtime.json`.

## 2. Tasks and comparison

Three maze-solver **coding tasks**, not reinforcement-learning navigation episodes:

1. **Unweighted:** shortest orthogonal path through open cells.
2. **Weighted:** minimum entering-cell cost; zero-cost cells are blocked and the start cost is excluded.
3. **Keys/doors:** shortest escape while collecting reusable keys and opening matching doors; search must retain key inventory in its state.

Each clean Git seed deliberately returned `None`. Only `maze.py` could mutate. Each family had four public examples in two development checks and 96 fixed generated protected examples in two final checks. Operator-owned reference algorithms generated the expected answers before search.

The six-treatment order was frozen in advance:

`unweighted-1round → weighted-3round → keys-1round → unweighted-3round → weighted-1round → keys-3round`.

Numeric generation limits were one or three; proposal-call budgets equaled those limits. Goal-based early stopping was deliberately disabled to exercise the requested number of generations. Allocation and final tie draws were exact zero draws. There were no operator retries or candidate repairs within either batch.

**One round is not one model completion.** A proposal can include several model-driven inspect/edit/test actions inside the selected harness. The comparator is one-round Agentvolve, not plain Pi or an equal-compute baseline.

The same sealed harness candidate was used for every maze treatment:

- Candidate: `5ac7d8c077ad3121cf263ed6465176e5750b2c95b80444a83344f076be283d5d`.
- Descriptor: `/mnt/Tforce/dev/metering-live-runs/harness-pi-20260902T213803822Z/selected-harness.json`.
- Descriptor SHA-256: `44936fc7c20e635ae68075be8417bf4f2f194f4eff69633226f07dcaa5b60d85`.

Each treatment used an isolated Pi RPC session with the explicit Agentvolve extension and without ambient context/tools. The workflow was invoked through `/goal`, `/limit N generations`, and `/agentvolve`. Qwen generated the mutations; the operator did not write or repair evolved solutions.

## 3. Corrected-batch results

Search interval: **16:05:58–17:02:24 UTC**. Protected outcomes were not inspected until all six scheduled search attempts finished.

### Independent protected correctness

| Maze family | Unchanged `None` seed | One round | Three rounds | Additional correct answers from three rounds |
|---|---:|---:|---:|---:|
| Unweighted | 14/96 | **96/96** | **96/96** | 0 |
| Weighted | 19/96 | **96/96** | **96/96** | 0 |
| Keys/doors | 18/96 | **96/96** | **96/96** | 0 |

The seed matches unreachable cases by returning `None`; its nonzero score is not pathfinding ability. Each seed passed 1/4 individual public examples, but 0/2 complete development groups. Every selected solution passed 4/4 public examples and both protected groups.

Thus, generating a first solution clearly improved over the broken seed. **The extra evolutionary rounds did not improve the measured accuracy over a single proposed solution.**

### Execution, cost, and inheritance

Token figures below are recorded successful mutation input plus output tokens, not complete search-cost accounting.

| Treatment | Completed rounds / limit | Recorded model calls | Recorded mutation tokens | Workflow minutes | Selected lineage depth |
|---|---:|---:|---:|---:|---:|
| Unweighted, one round | 1/1 | 4 | 16,668 | 4.25 | 1 |
| Unweighted, three rounds | 3/3 | 10 | 49,829 | 9.98 | 3 |
| Weighted, one round | 1/1 | 5 | 44,310 | 11.96 | 1 |
| Weighted, three rounds | 3/3 | 12 | 74,701 | 16.44 | 2 |
| Keys/doors, one round | 1/1 | 3 | 13,531 | 3.10 | 1 |
| Keys/doors, three rounds | 3/3 | 9 | 46,942 | 10.69 | 3 |
| **All one-round treatments** | **3/3** | **12** | **74,509** | **19.31** | — |
| **All three-round treatments** | **9/9** | **31** | **171,472** | **37.11** | — |

All six have a verified final seal and an applicable patch. The three-round runs contain real parent-child inheritance, rather than merely relabeling a single candidate as multiple generations. The weighted run also branched from the seed in round two before selecting a descendant in round three.

Every first challenger already passed both public development groups. All subsequent challengers also passed both groups: there was no observed development pass-count improvement after the first solution either.

The inspected three-round programs are ordinary BFS, Dijkstra, and BFS over `(cell, key-mask)`, respectively. This is credible solver generation, but the tasks reached a correctness ceiling too early to demonstrate an evolutionary advantage.

Selected commits, relative to each treatment's `candidate.git`:

| Treatment | Selected commit |
|---|---|
| Unweighted, one round | `d890061563ca3a92f9795829fee60705e154ebcd` |
| Unweighted, three rounds | `7973bb5b1328a0a458909a7e83702043f0e06dd6` |
| Weighted, one round | `2f69ebb4e9923f39f9af9fe054f761ac4eefd34a` |
| Weighted, three rounds | `0fbed1c7df6ab1a8a84a0a0e44ae2c140832a6f3` |
| Keys/doors, one round | `9e3144ded50e57734e09316a1bb86b84bd003732` |
| Keys/doors, three rounds | `0520034320d3fb5d17a5b6fdcdcaa81b9bfc32ce` |

## 4. Failures and the benchmark correction

### Fresh Level-2 harness attempt

The fresh harness attempt took **33.96 minutes**. One development round completed: incumbent and challenger both passed 5/5 development cases. The second Controller attempt failed and left an explicit pending intent:

`Controller attempt requires explicit retry: exit`

Two proposal calls were recorded; no protected final evaluation began and no new selected harness was published. The preregistered historical fallback was used. No retry was performed.

This is a real incomplete workflow attempt, not a successful harness-evolution result. The durable diagnostic does not establish the underlying subprocess failure cause.

### Initial maze batch: authoring error, not evidence against maze capability

Initial search interval: **14:36:51–15:55:00 UTC**, including the harness attempt.

| Initial treatment | Completed development rounds | Outcome |
|---|---:|---|
| Unweighted, one round | 1 | Protected profile rejected: oversized argv element |
| Weighted, three rounds | 3 | Same configuration error |
| Keys/doors, one round | 1 | Same configuration error |
| Unweighted, three rounds | 3 | Same configuration error |
| Weighted, one round | 1 | Same configuration error |
| Keys/doors, three rounds | 0 | Controller attempt failed; explicit pending intent |

**The benchmark author—this assistant—put oversized inline Python programs into the protected profiles.** Their arguments ranged from 4,850 to 9,344 characters; `apps/coding_agent/protocol.py::_checks` permits at most 4,096 characters per argument. The public profiles were valid, but the protected profiles were not explicitly validated before this first batch.

Five runs therefore stopped with `protected coding final checks[0].argv is malformed` after doing useful development work. No final experiment was declared in these initial maze runs. They are invalid benchmark configurations, not five demonstrated failures to solve mazes. The separate initial keys proposal failure remains recorded as a genuine incomplete attempt.

The original runs, pending intents, and analysis were retained. A **new, separately preregistered corrective batch** repeated all six treatments from the original unchanged seeds. Only protected command transport changed: the identical Python check programs were encoded with base64/zlib, bringing argument lengths to 1,722–3,230 characters. Decompression was checked byte-for-byte against the original programs. All task and protected profiles were explicitly validated, and the transport was tested in the pinned Docker image before new inference.

No maze, expected answer, public check, goal, seed commit, treatment order, budget, model, or selected harness changed. No evolved candidate was repaired or reused as a seed. The correction was driven by schema rejection, not protected accuracy. See `prepare_corrected.py` and `corrected/transport-equivalence.json`.

## 5. Independent verification

Workflow exit codes alone are insufficient evidence of correctness. The post-search auditor therefore:

1. Verified preregistration and unchanged seed HEADs/worktrees.
2. Ran the public offline solution verifier against each completed run and checked mutation-receipt content hashes.
3. Loaded the already-selected immutable commit into a **fresh Docker `KernelSession`**; no candidate code was executed on the host.
4. Supplied only the 100 test inputs to the candidate process. Expected answers remained outside that process.
5. Required valid structured output, exactly one answer per input, exact integer/`None` agreement, and unchanged input values. An empty successful exit could not pass this audit.
6. Checked each published patch with `git apply --check`, without applying it.

All six corrective runs passed. These tests establish the recorded examples, not formal correctness or complete adversarial evaluator security.

Additional offline Driver/solution replays left **1,201 regular run files unchanged**, including 486 files across the corrected runs, 616 across the initial maze runs, and 99 in the failed fresh harness run. Driver verification of a valid pending prefix must not be confused with a completed experiment.

`corrected/audit/` contains raw audit outputs, verifier output, replay checks, and extracted selected source. `report-data.json` contains the aggregated measurements and lineage evidence.

## 6. Accounting and operational findings

- The corrective runs recorded **245,981 mutation tokens across 43 model calls**, while every solution Driver's candidate-evaluation token total was **zero**. That is consistent with the current separation: mutation inference is not candidate execution/evaluation cost. Zero must not be presented as total search expenditure.
- Across both maze batches and the fresh harness's completed candidate assays, receipts cover **518,130 tokens and 115 model calls**. This excludes outer harness-proposal inference and any unreceipted failed/retried inference. Cached-token counters are not fully aggregated by the connector bridge. These are incomplete recorded usage totals, not a complete bill or energy/GPU-cost measurement.
- Timed experiment operations totaled approximately **134.6 minutes**: 34.0 fresh harness, 44.2 initial maze attempts, and 56.4 corrective maze operations. Setup, correction, operator work, and post-search audits are additional. The erroneous initial configuration consumed real resources and is not hidden from these totals.
- Failed subprocess diagnostics lose important detail: `JsonProcessError` retains stderr/return code, but `machine.py::error_detail` records only its string form, here `exit`. The underlying causes of the two pending attempts cannot be established from these durable diagnostics. A future improvement should preserve bounded forensic diagnostics separately from optimizer-visible feedback.
- No accounting, evaluator, selection, retry, or status behavior was modified for this study. Full search-cost accounting remains deferred.

## 7. What this does and does not show

**Supported:** with a compatible sealed harness and valid profiles, the current Level-1 pipeline can use local Qwen3.8 on llama.cpp/ROCm to generate correct maze solvers, preserve real commit ancestry, execute independent checks, publish patches, and replay the evidence offline.

**Not supported:** that three rounds improve these solutions over one round; that Agentvolve beats ordinary Pi or equal-compute alternatives; that fresh Level-2 evolution is reliably turnkey; or that these small coding tasks demonstrate general self-improvement.

There is one run per family/budget cell, only three families, no ordinary-Pi or best-of-N control, unequal inference expenditure, non-random allocation draws, and no fixed model sampling seed. Ninety-six examples per artifact are **not** ninety-six independent optimization runs. The reused harness's historical model-weight identity is not retroactively established by the current run's file fingerprints.

A useful next study would first ensure valid operator preflight and adequate failure diagnostics, then use harder below-ceiling tasks, multiple independent runs, and equalized inference budgets to compare ordinary Pi, best-of-N, and actual lineage-based evolution. No such superiority experiment was performed here.

## 8. Evidence index

All paths below are relative to the local evidence archive identified above, not this documentation directory. Generated study state is intentionally excluded from Git.

- Initial preregistration: `preregistration.json`, SHA-256 `325ab719f2605eaf525e0d75fab60f4f1ac006e1e1ba636470e84b0e5cc5ab33`.
- Corrective preregistration: `corrected/preregistration.json`, SHA-256 `879bff86cfaf0ae9e487042e61b4a4321fa84e5ff03e4282217aa166ec25edbb`.
- Runtime/provenance: `runtime.json`, `preflight.json`, `postflight.json`, `hardware.json`, `server-props.json`.
- Methods: `setup_study.py`, `run_study.py`, `audit_study.py`, `prepare_corrected.py`, `corrected/run_study.py`, `corrected/audit_study.py`, `finalize_data.py`.
- Initial audit version and the documented missing-report handling change: `audit_study.v1.py`, `audit-method-note.json`.
- Execution/error logs: `execution.json`, `logs/`, `corrected/execution.json`, `corrected/logs/`.
- Initial analysis: `analysis.json`; main valid-batch analysis: `corrected/analysis.json`.
- Aggregated report data: `report-data.json`; integrity/replay output: `audit/read-only-replay/`, `corrected/audit/read-only-replay/`.
- Immutable run artifacts and patches: `runs/` and `corrected/runs/`.

No further searches were launched after protected analysis. No generated patch was applied to the original repositories.
