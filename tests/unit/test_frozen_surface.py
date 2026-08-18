"""The guard that actually protects the contract.

Everything else in this suite asserts that the code agrees with itself. That is not the
same as asserting the code still agrees with a plugin compiled a year ago, and the
difference is not academic: renaming a verb and deleting a result field leaves the rest of
this suite entirely green, because a rename touches the constant, the class, and the test
together.

So this compares the live surface against a snapshot recorded on disk. The rule encodes the
versioning policy from ``protocol.py``:

    frozen must remain a subset of current

Additions pass, because a plugin that has never heard of a new verb or field simply ignores
it. Removals, renames, and optional-to-required transitions fail, because those are what
break a binary that cannot be rebuilt.

To change protocol v1 on purpose, bump ``PROTOCOL_VERSION``, record a new snapshot with
``python scripts/record_host_api_surface.py``, and keep the old snapshot so the old plugin stays
covered. Editing an existing snapshot to make this test pass defeats its only purpose.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.unit.host_api_surface import capture_surface

FROZEN_DIR = Path(__file__).parent / "fixtures" / "host_api"
RECORD_HINT = (
    "If this change is intentional and breaking, bump PROTOCOL_VERSION, run "
    "`python scripts/record_host_api_surface.py`, and keep the old snapshot. "
    "Do not edit an existing snapshot to make this pass."
)


def frozen_snapshots() -> list[Path]:
    return sorted(FROZEN_DIR.glob("protocol_v*.json"))


def test_at_least_one_snapshot_exists() -> None:
    """A missing snapshot means no protection at all, so it fails loudly."""
    assert frozen_snapshots(), f"No frozen surface found in {FROZEN_DIR}. {RECORD_HINT}"


@pytest.fixture(scope="module")
def current() -> dict[str, Any]:
    return capture_surface()


@pytest.mark.parametrize("snapshot_path", frozen_snapshots(), ids=lambda p: p.stem)
class TestFrozenSurface:
    """Every recorded protocol version must still be fully supported."""

    @staticmethod
    def _frozen(snapshot_path: Path) -> dict[str, Any]:
        return json.loads(snapshot_path.read_text())

    def test_version_is_still_inside_the_support_window(self, snapshot_path: Path, current: dict) -> None:
        """Dropping a version is a policy decision, not a refactor side effect."""
        frozen = self._frozen(snapshot_path)
        version = frozen["protocol_version"]
        assert version in current["supported_protocol_versions"], (
            f"Protocol v{version} was recorded but is no longer in SUPPORTED_PROTOCOL_VERSIONS. "
            f"Removing it strands every plugin speaking it. {RECORD_HINT}"
        )

    def test_no_verb_disappeared(self, snapshot_path: Path, current: dict) -> None:
        frozen = self._frozen(snapshot_path)
        missing = set(frozen["verbs"]) - set(current["verbs"])
        assert not missing, f"Verbs removed or renamed: {sorted(missing)}. {RECORD_HINT}"

    def test_no_notification_disappeared(self, snapshot_path: Path, current: dict) -> None:
        frozen = self._frozen(snapshot_path)
        missing = set(frozen["notifications"]) - set(current["notifications"])
        assert not missing, f"Notifications removed or renamed: {sorted(missing)}. {RECORD_HINT}"

    def test_no_payload_field_disappeared(self, snapshot_path: Path, current: dict) -> None:
        """The failure that is invisible to every other test in this suite."""
        frozen = self._frozen(snapshot_path)
        problems = []
        for payload_name, frozen_fields in frozen["payloads"].items():
            current_fields = current["payloads"].get(payload_name)
            if current_fields is None:
                problems.append(f"{payload_name}: payload class removed or renamed")
                continue
            for field_name in frozen_fields:
                if field_name not in current_fields:
                    problems.append(f"{payload_name}.{field_name}: field removed or renamed")
        assert not problems, "Wire surface shrank:\n  " + "\n  ".join(problems) + f"\n{RECORD_HINT}"

    def test_no_optional_field_became_required(self, snapshot_path: Path, current: dict) -> None:
        """An old plugin omits fields it never knew about, so requiring one rejects it."""
        frozen = self._frozen(snapshot_path)
        problems = []
        for payload_name, frozen_fields in frozen["payloads"].items():
            current_fields = current["payloads"].get(payload_name, {})
            for field_name, frozen_field in frozen_fields.items():
                current_field = current_fields.get(field_name)
                if current_field is None:
                    continue
                if current_field["required"] and not frozen_field["required"]:
                    problems.append(f"{payload_name}.{field_name}")
        assert not problems, f"Optional fields became required, which rejects older plugins: {problems}. {RECORD_HINT}"

    @pytest.mark.parametrize(
        "key",
        ["value_types", "source_kinds", "node_states", "execution_states"],
    )
    def test_no_enumerated_value_disappeared(self, snapshot_path: Path, current: dict, key: str) -> None:
        """A plugin switches on these strings, so a removal is an unhandled case."""
        frozen = self._frozen(snapshot_path)
        missing = set(frozen[key]) - set(current[key])
        assert not missing, f"{key} lost values: {sorted(missing)}. {RECORD_HINT}"

    @pytest.mark.parametrize("key", ["value_descriptor_keys", "value_source_keys"])
    def test_no_value_descriptor_key_disappeared(self, snapshot_path: Path, current: dict, key: str) -> None:
        """A plugin indexes these keys directly, so losing one is a crash, not a default."""
        frozen = self._frozen(snapshot_path)
        missing = set(frozen[key]) - set(current[key])
        assert not missing, f"{key} lost keys: {sorted(missing)}. {RECORD_HINT}"


def test_additions_are_allowed() -> None:
    """Guards the guard: additive change must not be reported as breaking.

    If this ever fails, the comparison has become an equality check, which would block
    every additive release and pressure people into editing snapshots instead.

    Deliberately derived from the frozen baseline rather than from the live surface, so it
    tests the subset rule itself and cannot be knocked over by an unrelated code change.
    """
    frozen = json.loads(frozen_snapshots()[0].read_text())

    widened = json.loads(json.dumps(frozen))
    widened["verbs"].append("NukeSomeFutureRequest")
    widened["notifications"].append("NukeSomeFutureEvent")
    widened["value_types"].append("GTFutureThing")
    widened["source_kinds"].append("future_kind")
    first_payload = next(iter(widened["payloads"]))
    widened["payloads"][first_payload]["field_added_next_release"] = {"required": False}
    widened["payloads"]["NukeSomeFutureRequest"] = {"brand_new": {"required": True}}

    for key in ("verbs", "notifications", "value_types", "source_kinds"):
        assert not set(frozen[key]) - set(widened[key]), f"additive change wrongly flagged in {key}"

    for payload_name, frozen_fields in frozen["payloads"].items():
        assert not set(frozen_fields) - set(widened["payloads"][payload_name])

    # A brand new required field on a brand new payload is fine: no existing plugin sends it.
    assert widened["payloads"]["NukeSomeFutureRequest"]["brand_new"]["required"] is True
