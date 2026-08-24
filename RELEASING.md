# Releasing Metering

Git tags published as GitHub Releases are the source of package versions. Do
not hard-code a package version in `pyproject.toml`, `src/metering/`, or
`src/evo/`.

## Version format

Use a numeric semantic-version tag:

```text
MAJOR.MINOR.PATCH
```

`setuptools-scm` derives package metadata from the checked-out tag. Untagged
development builds receive a generated development version.

The replacement of the historical hidden-fault harness is a breaking release.
Old run artifacts require the historical commit that created them; the new
package does not include a replay compatibility layer.

## Release checks

Start from a clean branch synchronized with its remote, then run:

```bash
uv run --extra test pytest -q
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | uv run metering
history_dir="$(mktemp -d)"
printf '%s\n' '{"measure":"entropy","probabilities":[0.5,0.5]}' \
  | uv run metering-history record "$history_dir"
uv run metering-history verify "$history_dir"
uv run python - <<'PY'
from evo import Candidate, Verdict, step

parent = Candidate("parent", 1)
transition = step(
    parent,
    lambda _: Candidate("child", 2),
    lambda incumbent, challenger: Verdict(challenger.id, {"passed": True}),
)
assert transition.next_parent.value == 2
PY
uv build
```

The measurement smoke check must emit a finite entropy value of `1.0` at base
`2.0`; the history smoke check must record and verify one pair; the Evo smoke
check must select the challenger.

The wheel should contain the four-module `metering` package, the one-file `evo`
package, and packaging metadata. The source archive also contains tests,
Markdown sources, build configuration, and the non-packaged applications under
`apps/`. Inspect both archives for legacy harness modules, generated application
runs or sandboxes, caches, and other build output; none belongs in a release.

Create and push an annotated numeric tag only after those checks pass:

```bash
git tag -a 1.0.0 -m "Release 1.0.0"
git push origin 1.0.0
```

Do not move an existing release tag. Publish a new version when a release needs
correction.
