# Releasing Metering

Git tags published as GitHub Releases are the source of package versions. Do
not hard-code a package version in `pyproject.toml` or `src/metering/`.

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
uv build
```

The CLI smoke check must emit a finite entropy value of `1.0` at base `2.0`.
The wheel should contain only the three public package modules and packaging
metadata. The source archive normally also contains tests, Markdown sources,
and build configuration. Inspect both archives for legacy harness modules,
generated runs, caches, or other build output; none belongs in a release.

Create and push an annotated numeric tag only after those checks pass:

```bash
git tag -a 1.0.0 -m "Release 1.0.0"
git push origin 1.0.0
```

Do not move an existing release tag. Publish a new version when a release needs
correction.
