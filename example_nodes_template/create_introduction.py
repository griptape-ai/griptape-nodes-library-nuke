from typing import Any

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import ControlNode


# Control Nodes import the ControlNode class.
class CreateIntroduction(ControlNode):
    def __init__(self, name: str, metadata: dict[str, Any] | None = None, **kwargs) -> None:
        node_metadata = {"category": "ControlNodes", "description": "Create an introduction."}
        if metadata:
            node_metadata.update(metadata)
        super().__init__(name=name, metadata=node_metadata, **kwargs)

        self.add_parameter(
            Parameter(
                name="full_name",
                input_types=["str"],
                type="str",
                output_type="str",
                # If you don't specify allowed_modes, it defaults to all three modes being allowed (INPUT, OUTPUT, and PROPERTY)
                allowed_modes={ParameterMode.PROPERTY, ParameterMode.INPUT},
                tooltip="The name of the user",
            )
        )
        self.add_parameter(
            Parameter(
                name="age",
                input_types=["int", "float"],
                type="int",
                output_type="int",
                default_value=30,
                tooltip="What is your age",
            )
        )
        self.add_parameter(
            Parameter(
                name="introduction",
                output_type="str",
                tooltip="The user's introduction",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"multiline": True},
            )
        )

    def process(self) -> None:
        # All of the current values of a parameter are stored on self.parameter_values (If they have an INPUT or PROPERTY)
        full_name = self.parameter_values["full_name"]
        age = self.parameter_values["age"]
        # All output values should be set in self.parameter_output_values.
        introduction = f"Hey! My name is {full_name}, and I'm {age} years old."
        self.parameter_output_values["introduction"] = introduction
        # The node is complete!
