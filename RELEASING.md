# Releasing Metering

Git tags published as GitHub Releases are the source of package release versions. Do not add a hard-coded package version to `pyproject.toml` or `src/metering/`.

## Version format

Use a numeric semantic version tag without a phase prefix:

```text
MAJOR.MINOR.PATCH
```

Examples are `1.0.0` and `1.1.0`. `setuptools-scm` derives package metadata from the checked-out tag. Untagged development builds receive a generated development version.

Package release versions identify a published build. Replay compatibility is gated separately by the controller, verifier, and meter versions plus strict schema decoders. World, instance, and policy declarations remain recorded and cross-checked within each artifact set. Bump the relevant replay-gated component version whenever its interpretation changes.

## Publish a release

1. Start from a clean `main` branch synchronized with `origin/main`.
2. Run the full tests and a fresh calibration.
3. Build the wheel and source archive locally.
4. Create an annotated numeric tag.
5. Push the tag to GitHub.

```bash
uv run --extra test pytest -q
uv run python -m metering calibrate --output /tmp/metering-release-check
uv build
git tag -a 1.0.0 -m "Release 1.0.0"
git push origin 1.0.0
```

The `.github/workflows/release.yml` workflow builds packages from the tag and creates the matching GitHub Release with generated notes.

Do not move an existing release tag. Publish a new version when a release needs correction.
