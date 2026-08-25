"""Evolve one Pi-style skill through an external proposer-and-judge adapter."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shlex
from pathlib import Path

from evo import Candidate, Verdict, step


ADAPTER_TIMEOUT_SECONDS = 60


def canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def skill_id(text: str) -> str:
    payload = canonical_json({"schema": "pi-skill-v1", "text": text})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def skill_candidate(text: str) -> Candidate[str]:
    if not text:
        raise ValueError("skill text must not be empty")
    return Candidate(skill_id(text), text)


async def call_adapter(command: list[str], request: dict[str, object]) -> dict[str, object]:
    if not command:
        raise ValueError("adapter command must not be empty")
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate((canonical_json(request) + "\n").encode("utf-8")),
            timeout=ADAPTER_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError("adapter timed out") from None

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"adapter exited with {process.returncode}")
    if stderr:
        raise RuntimeError("adapter wrote unexpected standard error")

    try:
        response = json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("adapter returned invalid UTF-8 JSON") from exc
    if type(response) is not dict:
        raise RuntimeError("adapter response must be one JSON object")
    return response


async def evolve_skill(
    parent_text: str,
    adapter_command: list[str],
) -> dict[str, object]:
    parent = skill_candidate(parent_text)

    async def propose(incumbent: Candidate[str]) -> Candidate[str]:
        response = await call_adapter(
            adapter_command,
            {
                "action": "propose",
                "candidate": {"id": incumbent.id, "text": incumbent.value},
            },
        )
        candidate = response.get("candidate")
        if type(candidate) is not dict or set(candidate) != {"id", "text"}:
            raise RuntimeError("propose response must contain exactly candidate.id and candidate.text")
        candidate_id = candidate["id"]
        text = candidate["text"]
        if type(candidate_id) is not str or type(text) is not str:
            raise RuntimeError("proposed candidate id and text must be strings")
        proposed = skill_candidate(text)
        if proposed.id != candidate_id:
            raise RuntimeError("proposed candidate id does not match its skill text")
        return proposed

    async def judge(
        incumbent: Candidate[str],
        challenger: Candidate[str],
    ) -> Verdict[object]:
        response = await call_adapter(
            adapter_command,
            {
                "action": "judge",
                "parent": {"id": incumbent.id, "text": incumbent.value},
                "challenger": {"id": challenger.id, "text": challenger.value},
            },
        )
        if set(response) != {"selected_id", "evidence"}:
            raise RuntimeError("judge response must contain exactly selected_id and evidence")
        selected_id = response["selected_id"]
        if type(selected_id) is not str:
            raise RuntimeError("judge selected_id must be a string")
        return Verdict(selected_id, response["evidence"])

    transition = await step(parent, propose, judge)
    return {
        "parent": {"id": transition.parent.id, "text": transition.parent.value},
        "challenger": {
            "id": transition.challenger.id,
            "text": transition.challenger.value,
        },
        "selected_id": transition.verdict.selected_id,
        "next_parent": {
            "id": transition.next_parent.id,
            "text": transition.next_parent.value,
        },
        "evidence": transition.verdict.evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", type=Path, required=True)
    parser.add_argument(
        "--adapter",
        required=True,
        help="command implementing the propose/judge JSON protocol",
    )
    args = parser.parse_args()
    command = shlex.split(args.adapter)
    result = asyncio.run(evolve_skill(args.skill.read_text(encoding="utf-8"), command))
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
