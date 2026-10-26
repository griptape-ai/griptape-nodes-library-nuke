"""Guards the engine version floor against drift between the library manifest and pyproject.toml.

The manifest's engine_version is what the engine checks before loading the library; the
dev-group floor in pyproject.toml is what the test suite is resolved and run against. If the
manifest falls behind, an engine the library no longer works on still loads it.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parents[2]


def _pyproject_engine_floor() -> str:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    for dependency in pyproject["dependency-groups"]["dev"]:
        requirement = Requirement(dependency)
        if requirement.name == "griptape-nodes-engine":
            (specifier,) = (s for s in requirement.specifier if s.operator == ">=")
            return specifier.version
    raise AssertionError("pyproject.toml declares no griptape-nodes-engine floor in the dev group")


def test_manifest_engine_version_matches_the_pyproject_floor() -> None:
    manifest = json.loads((REPO_ROOT / "griptape-nodes-library.json").read_text())
    assert manifest["metadata"]["engine_version"] == _pyproject_engine_floor()
