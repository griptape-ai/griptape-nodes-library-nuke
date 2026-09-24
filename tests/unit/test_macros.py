"""Tests for macro path resolution.

Two systems share the `{...}` syntax, so the risk is not failing to resolve, it is resolving
the wrong thing or handing a host an unresolved template as a path to open.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from griptape.artifacts import ImageUrlArtifact
from griptape_nodes.retained_mode.events.project_events import (
    GetPathForMacroResultFailure,
    GetPathForMacroResultSuccess,
    PathResolutionFailureReason,
    UnresolvedSequenceSlotBehavior,
)

from nuke_host_api import value_types
from nuke_host_api.protocol import ValueType
from nuke_host_api.value_types import UnrepresentableValueError


class FakeEngine:
    """Stands in for the GriptapeNodes facade, recording what was asked of it."""

    def __init__(self, resolved: str | None) -> None:
        self._resolved = resolved
        self.requests: list[Any] = []

    def handle_request(self, request: Any) -> Any:
        self.requests.append(request)
        if self._resolved is None:
            return GetPathForMacroResultFailure(
                failure_reason=PathResolutionFailureReason.MISSING_REQUIRED_VARIABLES,
                missing_variables={"MY_VAR"},
                result_details="missing required variables",
            )
        return GetPathForMacroResultSuccess(
            resolved_path=Path(self._resolved),
            absolute_path=Path(self._resolved),
            result_details="resolved",
        )


@pytest.fixture
def resolving_engine(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Install a fake engine that resolves macros to a fixed path."""

    def install(resolved: str | None) -> FakeEngine:
        engine = FakeEngine(resolved)
        monkeypatch.setattr(value_types, "GriptapeNodes", engine)
        return engine

    return install


def test_a_macro_resolves_to_an_absolute_path(resolving_engine) -> None:  # noqa: ANN001
    resolving_engine("/workspace/outputs/render.png")
    descriptor = value_types.normalize_value("{outputs}/render.png", "ImageUrlArtifact")
    assert descriptor["value"] == {"path": "/workspace/outputs/render.png", "format": "png"}


def test_a_sequence_slot_is_rendered_as_hash_padding(resolving_engine) -> None:  # noqa: ANN001
    """A Read node expands `####` itself; the engine's default of FAIL would reject every sequence."""
    engine = resolving_engine("/workspace/outputs/render.####.exr")
    descriptor = value_types.normalize_value("{outputs}/render.{###}.exr", "ImageUrlArtifact")
    assert descriptor["value"] == {"path": "/workspace/outputs/render.####.exr", "format": "exr"}
    assert (
        engine.requests[0].unresolved_sequence_slot_behavior == UnresolvedSequenceSlotBehavior.RENDER_SEQUENCE_PATTERN
    )


def test_an_unresolvable_path_template_is_never_handed_over_as_a_path(resolving_engine) -> None:  # noqa: ANN001
    """The failure mode that matters: a host opening a literal `{...}` string."""
    resolving_engine(None)
    with pytest.raises(UnrepresentableValueError, match=r"\{MY_VAR\}/plate\.exr"):
        value_types.normalize_value("{MY_VAR}/plate.exr", "str")


def test_a_macro_inside_an_artifact_value_resolves_too(resolving_engine) -> None:  # noqa: ANN001
    resolving_engine("/workspace/outputs/from_artifact.png")
    descriptor = value_types.normalize_value(ImageUrlArtifact("{outputs}/from_artifact.png"), "ImageUrlArtifact")
    assert descriptor["value_type"] == ValueType.IMAGE
    assert descriptor["value"]["path"] == "/workspace/outputs/from_artifact.png"


def test_a_macro_in_each_list_item_resolves(resolving_engine) -> None:  # noqa: ANN001
    resolving_engine("/workspace/outputs/frame.png")
    descriptor = value_types.normalize_value(["{outputs}/frame.png", "{outputs}/frame.png"], "list[str]")
    assert [entry["path"] for entry in descriptor["value"]] == ["/workspace/outputs/frame.png"] * 2


def test_a_plain_path_never_reaches_the_macro_resolver(resolving_engine) -> None:  # noqa: ANN001
    engine = resolving_engine("/should/not/be/used")
    value_types.normalize_value("/mnt/show/plate.exr", "str")
    assert engine.requests == []


def test_prose_containing_braces_stays_text(resolving_engine) -> None:  # noqa: ANN001
    resolving_engine(None)
    descriptor = value_types.normalize_value("render {frame} of the shot", "str")
    assert descriptor["value_type"] == ValueType.TEXT
    assert descriptor["value"] == "render {frame} of the shot"


def test_a_resolved_macro_path_uses_forward_slashes(resolving_engine) -> None:  # noqa: ANN001
    """Nuke's TCL layer treats backslashes as escapes, so a resolved path must not carry one."""
    resolving_engine("C:\\workspace\\outputs\\render.png")
    descriptor = value_types.normalize_value("{outputs}/render.png", "ImageUrlArtifact")
    assert descriptor["value"]["path"] == "C:/workspace/outputs/render.png"
