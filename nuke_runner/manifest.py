from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "griptape-nuke-runner/1.0"


@dataclass
class ManifestInput:
    path: str
    node: str

    def __post_init__(self) -> None:
        self.path = self.path.replace("\\", "/")


@dataclass
class ManifestOutput:
    path: str | list[str]
    node: str
    format: str = "png"
    type: str = "ImageArtifact"

    def __post_init__(self) -> None:
        if isinstance(self.path, list):
            self.path = [p.replace("\\", "/") for p in self.path]
        else:
            self.path = self.path.replace("\\", "/")


@dataclass
class KnobOverride:
    node: str
    knob: str
    value: Any


@dataclass
class JobManifest:
    script: str
    inputs: dict[str, ManifestInput] = field(default_factory=dict)
    outputs: dict[str, ManifestOutput] = field(default_factory=dict)
    knob_overrides: list[KnobOverride] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    frame_range: list[int] = field(default_factory=lambda: [1001, 1001])
    bake_output_path: str = ""
    schema: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.script = self.script.replace("\\", "/")
        self.bake_output_path = self.bake_output_path.replace("\\", "/")

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema": self.schema,
                "script": self.script,
                "frame_range": self.frame_range,
                "inputs": {k: {"path": v.path, "node": v.node} for k, v in self.inputs.items()},
                "outputs": {
                    k: {"path": v.path, "node": v.node, "format": v.format, "type": v.type}
                    for k, v in self.outputs.items()
                },
                "knob_overrides": [{"node": o.node, "knob": o.knob, "value": o.value} for o in self.knob_overrides],
                "env": self.env,
                "bake_output_path": self.bake_output_path,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, s: str) -> JobManifest:
        data = json.loads(s)
        if data.get("schema") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported manifest schema: {data.get('schema')!r}. Expected {SCHEMA_VERSION!r}.")
        return cls(
            schema=data["schema"],
            script=data["script"],
            frame_range=data.get("frame_range", [1001, 1001]),
            inputs={k: ManifestInput(path=v["path"], node=v["node"]) for k, v in data.get("inputs", {}).items()},
            outputs={
                k: ManifestOutput(
                    path=v["path"],
                    node=v["node"],
                    format=v.get("format", "png"),
                    type=v.get("type", "ImageArtifact"),
                )
                for k, v in data.get("outputs", {}).items()
            },
            knob_overrides=[
                KnobOverride(node=o["node"], knob=o["knob"], value=o["value"]) for o in data.get("knob_overrides", [])
            ],
            env=data.get("env", {}),
            bake_output_path=data.get("bake_output_path", ""),
        )
