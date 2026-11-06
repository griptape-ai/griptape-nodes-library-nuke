"""An in-memory stand-in for an open Nuke session, so the MCP tools have a comp to act on.

Nothing here talks to Nuke. The comp is seeded with a few problems that the bundled
`nuke-comp-review` skill knows to look for: a Write node rendering PNG in sRGB, a Write
frame range shorter than the plate, and a disabled Grade.
"""

from __future__ import annotations

import copy
import re
import time
from dataclasses import dataclass, field
from typing import Any

SHOW = "aurora"
SHOT = "sq010_sh0040"
SCRIPT_DIR = f"/shows/{SHOW}/{SHOT}/comp/nuke"
RENDER_DIR = f"/shows/{SHOW}/{SHOT}/comp/renders"

# Frames a render "takes", so a render looks like work without stalling the agent.
SECONDS_PER_FRAME = 0.01


@dataclass
class MockNode:
    name: str
    node_class: str
    inputs: list[str] = field(default_factory=list)
    knobs: dict[str, Any] = field(default_factory=dict)
    disabled: bool = False
    position: tuple[int, int] = (0, 0)

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "class": self.node_class,
            "inputs": list(self.inputs),
            "disabled": self.disabled,
        }

    def describe(self) -> dict[str, Any]:
        return {**self.summary(), "knobs": copy.deepcopy(self.knobs)}


@dataclass
class MockRender:
    write_node: str
    first_frame: int
    last_frame: int
    output_path: str
    script_version: int
    finished_at: float

    def describe(self) -> dict[str, Any]:
        return {
            "write_node": self.write_node,
            "frame_range": f"{self.first_frame}-{self.last_frame}",
            "frame_count": self.last_frame - self.first_frame + 1,
            "output_path": self.output_path,
            "script_version": f"v{self.script_version:03d}",
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.finished_at)),
        }


class MockNukeSession:
    def __init__(self) -> None:
        self.script_version = 12
        self.first_frame = 1001
        self.last_frame = 1096
        self.fps = 24.0
        self.format = "UHD_4K 3840x2160"
        self.working_colorspace = "ACES - ACEScg"
        self.current_frame = 1048
        self.unsaved_changes = False
        self.nodes: dict[str, MockNode] = {}
        self.renders: list[MockRender] = []
        self._seed()

    @property
    def script_path(self) -> str:
        return f"{SCRIPT_DIR}/{SHOT}_comp_v{self.script_version:03d}.nk"

    def script_info(self) -> dict[str, Any]:
        return {
            "script_path": self.script_path,
            "show": SHOW,
            "shot": SHOT,
            "script_version": f"v{self.script_version:03d}",
            "frame_range": f"{self.first_frame}-{self.last_frame}",
            "current_frame": self.current_frame,
            "fps": self.fps,
            "format": self.format,
            "working_colorspace": self.working_colorspace,
            "node_count": len(self.nodes),
            "unsaved_changes": self.unsaved_changes,
        }

    def list_nodes(self, node_class: str) -> list[dict[str, Any]]:
        wanted = node_class.strip().lower()
        return [node.summary() for node in self.nodes.values() if not wanted or node.node_class.lower() == wanted]

    def get_node(self, name: str) -> MockNode | None:
        return self.nodes.get(name)

    def set_knob(self, node: MockNode, knob: str, value: Any) -> Any:
        if knob == "disable":
            previous = node.disabled
            node.disabled = bool(value)
        else:
            previous = node.knobs.get(knob)
            node.knobs[knob] = value
        self.unsaved_changes = True
        return previous

    def create_node(self, node_class: str, name: str, input_node: str, knobs: dict[str, Any]) -> MockNode:
        final_name = name or self._next_name(node_class)
        inputs = [input_node] if input_node else []
        node = MockNode(final_name, node_class, inputs=inputs, knobs=dict(knobs))
        self.nodes[final_name] = node
        self.unsaved_changes = True
        return node

    def save_new_version(self) -> str:
        self.script_version += 1
        self.unsaved_changes = False
        for node in self.nodes.values():
            if node.node_class == "Write" and "file" in node.knobs:
                node.knobs["file"] = re.sub(r"_v\d{3}", f"_v{self.script_version:03d}", node.knobs["file"])
        return self.script_path

    def render(self, write_node: MockNode, first_frame: int, last_frame: int) -> MockRender:
        time.sleep((last_frame - first_frame + 1) * SECONDS_PER_FRAME)
        render = MockRender(
            write_node=write_node.name,
            first_frame=first_frame,
            last_frame=last_frame,
            output_path=str(write_node.knobs.get("file", "")),
            script_version=self.script_version,
            finished_at=time.time(),
        )
        self.renders.append(render)
        return render

    def _next_name(self, node_class: str) -> str:
        index = 1
        while f"{node_class}{index}" in self.nodes:
            index += 1
        return f"{node_class}{index}"

    def _seed(self) -> None:
        version = f"v{self.script_version:03d}"
        seed = [
            MockNode(
                "Read_plate",
                "Read",
                knobs={
                    "file": f"/shows/{SHOW}/{SHOT}/plates/{SHOT}_bg_v002.####.exr",
                    "first": 1001,
                    "last": 1096,
                    "colorspace": "ACES - ACES2065-1",
                },
            ),
            MockNode(
                "Read_fg_element",
                "Read",
                knobs={
                    "file": f"/shows/{SHOW}/{SHOT}/elements/{SHOT}_drone_fg_v004.####.exr",
                    "first": 1001,
                    "last": 1096,
                    "colorspace": "ACES - ACEScg",
                },
            ),
            MockNode("Denoise_plate", "Denoise2", inputs=["Read_plate"], knobs={"amount": 0.6}),
            MockNode(
                "Grade_plate_match",
                "Grade",
                inputs=["Denoise_plate"],
                knobs={"blackpoint": 0.002, "whitepoint": 0.95, "gain": [1.04, 1.0, 0.97], "gamma": 1.0},
                disabled=True,
            ),
            MockNode(
                "Roto_drone_garbage",
                "Roto",
                inputs=["Read_fg_element"],
                knobs={"shapes": 3, "feather": 4.0, "output": "alpha"},
            ),
            MockNode(
                "Merge_drone_over",
                "Merge2",
                inputs=["Grade_plate_match", "Roto_drone_garbage"],
                knobs={"operation": "over", "mix": 1.0},
            ),
            MockNode(
                "ZDefocus_lens",
                "ZDefocus2",
                inputs=["Merge_drone_over"],
                knobs={"size": 12.0, "focal_point": [1920, 1180], "max_size": 40},
            ),
            MockNode(
                "Write_comp",
                "Write",
                inputs=["ZDefocus_lens"],
                knobs={
                    "file": f"{RENDER_DIR}/{SHOT}_comp_{version}/{SHOT}_comp_{version}.####.png",
                    "file_type": "png",
                    "colorspace": "Output - sRGB",
                    "first": 1001,
                    "last": 1050,
                    "use_limit": True,
                },
            ),
        ]
        self.nodes = {node.name: node for node in seed}


_session = MockNukeSession()


def current_session() -> MockNukeSession:
    return _session


def reset_session() -> MockNukeSession:
    global _session  # noqa: PLW0603
    _session = MockNukeSession()
    return _session
