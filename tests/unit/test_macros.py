"""Tests for macro path resolution.

Macros matter because a host always needs a real path. Two systems share the `{...}`
syntax, so the risk is not failing to resolve, it is resolving the wrong thing or
labelling an unresolved template as a path a host will try to open.
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
from nuke_host_api.protocol import SourceKind, ValueType


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
    source = descriptor["sources"][0]
    assert source["kind"] == SourceKind.PATH
    assert source["value"] == "/workspace/outputs/render.png"
    assert source["format"] == "png"
    assert source["raw"] == "{outputs}/render.png"
    assert source["is_pattern"] is False


def test_a_sequence_macro_keeps_its_hash_padding_and_is_flagged(resolving_engine) -> None:  # noqa: ANN001
    """Nuke reads `####` natively, but it is not openable, so it must be labelled.

    The engine documents this rendering as presentation-only and warns it must not be
    handed to an I/O primitive. For a Read knob it is the correct form, so `is_pattern`
    distinguishes the two uses.
    """
    resolving_engine("/workspace/outputs/render.####.exr")
    descriptor = value_types.normalize_value("{outputs}/render.{###}.exr", "ImageUrlArtifact")
    source = descriptor["sources"][0]
    assert source["is_pattern"] is True
    assert "####" in source["value"]


def test_sequence_slots_are_requested_as_patterns_not_failures(resolving_engine) -> None:  # noqa: ANN001
    """The engine's default is FAIL, which would reject every sequence."""
    engine = resolving_engine("/workspace/outputs/render.####.exr")
    value_types.normalize_value("{outputs}/render.{###}.exr", "ImageUrlArtifact")
    request = engine.requests[0]
    assert request.unresolved_sequence_slot_behavior == UnresolvedSequenceSlotBehavior.RENDER_SEQUENCE_PATTERN


def test_an_unresolvable_macro_is_never_labelled_a_path(resolving_engine) -> None:  # noqa: ANN001
    """The failure mode that matters: a host opening a literal `{...}` string.

    Happens for an unsubstituted `{VAR}` workflow variable, since substitution can be
    disabled per-parameter or engine-wide.
    """
    resolving_engine(None)
    descriptor = value_types.normalize_value("{MY_VAR}/plate.exr", "ImageUrlArtifact")
    source = descriptor["sources"][0]
    assert source["kind"] == SourceKind.MACRO
    assert source["value"] == "{MY_VAR}/plate.exr"
    assert source["raw"] == "{MY_VAR}/plate.exr"


def test_a_macro_inside_an_artifact_value_resolves_too(resolving_engine) -> None:  # noqa: ANN001
    """Macros are not confined to bare strings."""
    resolving_engine("/workspace/outputs/from_artifact.png")
    descriptor = value_types.normalize_value(ImageUrlArtifact("{outputs}/from_artifact.png"), "ImageUrlArtifact")
    assert descriptor["value_type"] == ValueType.IMAGE
    assert descriptor["sources"][0]["kind"] == SourceKind.PATH
    assert descriptor["sources"][0]["value"] == "/workspace/outputs/from_artifact.png"


def test_a_plain_path_never_reaches_the_macro_resolver(resolving_engine) -> None:  # noqa: ANN001
    """No braces, no engine request. Keeps the common case free."""
    engine = resolving_engine("/should/not/be/used")
    value_types.normalize_value("/mnt/show/plate.exr", "str")
    assert engine.requests == []


def test_prose_containing_braces_does_not_become_a_path(resolving_engine) -> None:  # noqa: ANN001
    """Text is a legitimate value; a stray brace must not turn it into a locator."""
    resolving_engine(None)
    descriptor = value_types.normalize_value("render {frame} of the shot", "str")
    assert descriptor["sources"][0]["kind"] == SourceKind.MACRO
    assert descriptor["sources"][0]["value"] == "render {frame} of the shot"
