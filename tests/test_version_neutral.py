from __future__ import annotations

from pathlib import Path


def _maintained_files() -> list[tuple[Path, str]]:
    project = Path(__file__).resolve().parents[1]
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
    files: list[tuple[Path, str]] = []
    for root in roots:
        paths = [root] if root.is_file() else root.rglob("*") if root.exists() else []
        for path in paths:
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            files.append((path.relative_to(project), text))
    assert files
    return files


def test_current_tree_uses_release_versions_not_phase_label():
    forbidden = "v" + "0"
    for relative, text in _maintained_files():
        assert forbidden not in relative.as_posix().lower(), relative
        assert forbidden not in text.lower(), relative


def test_current_tree_avoids_size_minimizing_wording():
    forbidden = "sma" + "ll"
    for relative, text in _maintained_files():
        assert forbidden not in relative.as_posix().lower(), relative
        assert forbidden not in text.lower(), relative


def test_package_version_is_derived_from_git_tags():
    project = Path(__file__).resolve().parents[1]
    configuration = (project / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in configuration
    assert "setuptools-scm" in configuration
    assert "\nversion = \"" not in configuration
