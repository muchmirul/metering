from __future__ import annotations

from pathlib import Path


def test_current_tree_uses_release_versions_not_phase_label():
    project = Path(__file__).resolve().parents[1]
    forbidden = "v" + "0"
    roots = [
        project / "README.md",
        project / "PLAN.md",
        project / "RELEASING.md",
        project / "pyproject.toml",
        project / "src",
        project / "tests",
        project / "docs",
        project / ".github",
    ]

    checked = []
    for root in roots:
        paths = [root] if root.is_file() else root.rglob("*") if root.exists() else []
        for path in paths:
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            relative = path.relative_to(project)
            checked.append(relative)
            assert forbidden not in relative.as_posix().lower(), relative
            assert forbidden not in text.lower(), relative

    assert checked


def test_package_version_is_derived_from_git_tags():
    project = Path(__file__).resolve().parents[1]
    configuration = (project / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in configuration
    assert "setuptools-scm" in configuration
    assert "\nversion = \"" not in configuration
