from typing import Any

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import DataNode
from griptape_nodes.traits.widget import Widget


class CameraAnglePicker(DataNode):
    """Demo node showcasing a custom CameraControl UI component matching Qwen Image Edit Angles."""

    def __init__(self, name: str, metadata: dict[str, Any] | None = None, **kwargs) -> None:
        node_metadata = {
            "category": "DataNodes",
            "description": "Camera control component for rotation, tilt, and distance",
        }
        if metadata:
            node_metadata.update(metadata)
        super().__init__(name=name, metadata=node_metadata, **kwargs)

        self.add_parameter(
            Parameter(
                name="camera_angles",
                input_types=["dict"],
                type="dict",
                output_type="dict",
                default_value={"rotate_deg": 0, "move_forward": 0, "vertical_tilt": 0},
                tooltip="Camera angles: rotate_deg (-90 to 90), move_forward (0 to 10), vertical_tilt (-1 to 1)",
                allowed_modes={ParameterMode.PROPERTY, ParameterMode.OUTPUT},
                traits={Widget(name="AnglePicker", library="Example Library")},
            )
        )

    def process(self) -> None:
        angles = self.parameter_values.get("camera_angles", {})

        rotate_deg = angles.get("rotate_deg", 0)
        move_forward = angles.get("move_forward", 0)
        vertical_tilt = angles.get("vertical_tilt", 0)

        print(f"CameraControl - Rotation: {rotate_deg}°, Distance: {move_forward}, Tilt: {vertical_tilt}")

        self.parameter_output_values["camera_angles"] = angles
