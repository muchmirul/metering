# Releasing

Git tags published as GitHub Releases are the source of package versions. Do not
hard-code a package version in `pyproject.toml`, `src/metering/`, or `src/evo/`.

Use numeric semantic versions:

```text
MAJOR.MINOR.PATCH
```

Before tagging, run:

```bash
uv run --extra test pytest -q
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | uv run metering
history_dir="$(mktemp -d)"
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | uv run metering-history record "$history_dir"
uv run metering-history verify "$history_dir"
uv run python - <<'PY'
import asyncio
from evo import Candidate, Verdict, step

async def propose(_):
    return Candidate("child", 2)

async def judge(incumbent, challenger):
    return Verdict(challenger.id, {})

async def main():
    transition = await step(Candidate("parent", 1), propose, judge)
    assert transition.next_parent.value == 2

asyncio.run(main())
PY
uv build
```

The wheel must contain only the `metering` and `evo` packages plus packaging
metadata. Examples belong in the source archive, not the wheel.

Create an annotated tag only after the checks pass:

```bash
git tag -a 1.0.0 -m "Release 1.0.0"
git push origin 1.0.0
```

Never move an existing release tag.
