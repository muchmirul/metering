"""One deterministic fixture-evolution example using :func:`evo.step`."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
from collections.abc import Sequence

from evo import Candidate, Verdict, step
from metering import entropy, self_information


VERSIONS = ("v1", "v2", "v3", "v4")
PROBES = ("mode", "port")
RESULTS = {
    "v1": {"mode": "safe", "port": "8000"},
    "v2": {"mode": "safe", "port": "9000"},
    "v3": {"mode": "fast", "port": "8000"},
    "v4": {"mode": "fast", "port": "9000"},
}


def canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def make_candidate(genome: dict[str, object]) -> Candidate[dict[str, object]]:
    return Candidate(
        digest({"genome": genome, "schema": "fixture-genome-v1"}),
        dict(genome),
    )


def version_probabilities(genome: dict[str, object]) -> dict[str, float]:
    hypothesis = genome.get("hypothesis")
    confidence_bps = genome.get("confidence_bps")
    if hypothesis not in VERSIONS:
        raise ValueError("hypothesis must name one fixture version")
    if type(confidence_bps) is not int or not 2500 <= confidence_bps <= 10000:
        raise ValueError("confidence_bps must be an integer from 2500 to 10000")

    confidence = confidence_bps / 10000.0
    remainder = (1.0 - confidence) / (len(VERSIONS) - 1)
    return {
        version: confidence if version == hypothesis else remainder
        for version in VERSIONS
    }


def forecast(genome: dict[str, object], probe: str) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for version, probability in version_probabilities(genome).items():
        grouped.setdefault(RESULTS[version][probe], []).append(probability)
    return {
        result: math.fsum(probabilities)
        for result, probabilities in sorted(grouped.items())
    }


def result_entropy(versions: Sequence[str], probe: str) -> float:
    counts: dict[str, int] = {}
    for version in versions:
        result = RESULTS[version][probe]
        counts[result] = counts.get(result, 0) + 1
    total = len(versions)
    return entropy([count / total for count in counts.values()], base=2)


async def run_generation(
    *,
    active_version: str = "v3",
    required_improvement_bits: float = 0.05,
) -> dict[str, object]:
    if active_version not in VERSIONS:
        raise ValueError("active_version must be v1, v2, v3, or v4")
    if required_improvement_bits < 0:
        raise ValueError("required_improvement_bits must be non-negative")

    parent = make_candidate({"hypothesis": "v3", "confidence_bps": 5000})

    async def propose(
        incumbent: Candidate[dict[str, object]],
    ) -> Candidate[dict[str, object]]:
        child = dict(incumbent.value)
        child["confidence_bps"] = 7500
        return make_candidate(child)

    async def judge(
        incumbent: Candidate[dict[str, object]],
        challenger: Candidate[dict[str, object]],
    ) -> Verdict[dict[str, object]]:
        remaining = list(VERSIONS)
        unused = list(PROBES)
        cases: list[dict[str, object]] = []
        incumbent_losses: list[float] = []
        challenger_losses: list[float] = []

        while len(remaining) > 1:
            if not unused:
                raise RuntimeError("fixture probes cannot distinguish the versions")
            probe = max(
                unused,
                key=lambda item: result_entropy(remaining, item),
            )
            unused.remove(probe)

            # Both forecasts exist before the hidden target is revealed.
            incumbent_forecast = forecast(incumbent.value, probe)
            challenger_forecast = forecast(challenger.value, probe)
            target = RESULTS[active_version][probe]
            prior_versions = list(remaining)
            probe_entropy_bits = result_entropy(prior_versions, probe)

            incumbent_probability = incumbent_forecast[target]
            challenger_probability = challenger_forecast[target]
            incumbent_losses.append(self_information(incumbent_probability, base=2))
            challenger_losses.append(self_information(challenger_probability, base=2))

            prior_count = len(remaining)
            remaining = [
                version
                for version in remaining
                if RESULTS[version][probe] == target
            ]
            cases.append(
                {
                    "probe": probe,
                    "target": target,
                    "result_entropy_bits": probe_entropy_bits,
                    "remaining_before": prior_count,
                    "remaining_after": len(remaining),
                    "incumbent_target_probability": incumbent_probability,
                    "challenger_target_probability": challenger_probability,
                }
            )

        incumbent_mean = math.fsum(incumbent_losses) / len(incumbent_losses)
        challenger_mean = math.fsum(challenger_losses) / len(challenger_losses)
        improvement = incumbent_mean - challenger_mean
        selected_id = (
            challenger.id
            if improvement > required_improvement_bits
            else incumbent.id
        )
        return Verdict(
            selected_id,
            {
                "active_version": active_version,
                "cases": cases,
                "incumbent_mean_target_surprisal_bits": incumbent_mean,
                "challenger_mean_target_surprisal_bits": challenger_mean,
                "mean_improvement_bits": improvement,
                "required_improvement_bits": required_improvement_bits,
            },
        )

    transition = await step(parent, propose, judge)
    return {
        "parent": {"id": transition.parent.id, "value": transition.parent.value},
        "challenger": {
            "id": transition.challenger.id,
            "value": transition.challenger.value,
        },
        "selected_id": transition.verdict.selected_id,
        "next_parent": {
            "id": transition.next_parent.id,
            "value": transition.next_parent.value,
        },
        "evidence": transition.verdict.evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active", choices=VERSIONS, default="v3")
    parser.add_argument("--threshold", type=float, default=0.05)
    args = parser.parse_args()
    result = asyncio.run(
        run_generation(
            active_version=args.active,
            required_improvement_bits=args.threshold,
        )
    )
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
