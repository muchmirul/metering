from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_application(path: str, request: dict[str, object]) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(ROOT / path)],
        cwd=ROOT,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return json.loads(result.stdout)


def assay_report(candidate_id: str, probability: float) -> dict[str, object]:
    return run_application(
        "apps/forecast_assay/forecast_assay.py",
        {
            "schema_version": 1,
            "candidate": candidate_id,
            "evaluation": "weather/holdout-v1",
            "observations": [
                {
                    "observation": "case-1",
                    "target": "rain",
                    "target_probability": probability,
                }
            ],
        },
    )


def test_evolution_kernel_carries_mutator_content_ids_through_selection():
    mutation = run_application(
        "apps/mutator/mutator.py",
        {
            "schema_version": 1,
            "catalogue": {
                "loci": [
                    {"locus": "mode", "alleles": ["safe", "fast"]},
                ]
            },
            "parent_genome": {"mode": "safe"},
            "mutation_distribution": [
                {"locus": "mode", "allele": "fast", "probability": 1.0},
            ],
            "draw": 0.0,
        },
    )
    parent_id = mutation["parent"]["candidate_id"]
    child_id = mutation["child"]["candidate_id"]
    assert type(parent_id) is str
    assert type(child_id) is str

    incumbent_report = assay_report(parent_id, 0.5)
    challenger_report = assay_report(child_id, 0.75)
    assert incumbent_report["candidate"] == parent_id
    assert challenger_report["candidate"] == child_id

    decision = run_application(
        "apps/selection_gate/selection_gate.py",
        {
            "schema_version": 1,
            "incumbent_report": incumbent_report,
            "challenger_report": challenger_report,
            "required_improvement_bits": 0.05,
        },
    )

    assert decision["incumbent"] == parent_id
    assert decision["challenger"] == child_id
    assert decision["selected"] == child_id
    assert decision["decision"] == "promote_challenger"
