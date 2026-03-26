from typing import Any

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import DataNode


class CreateName(DataNode):
    def __init__(self, name: str, metadata: dict[str, Any] | None = None, **kwargs) -> None:
        node_metadata = {"category": "DataNodes", "description": "An example node with dependencies"}
        if metadata:
            node_metadata.update(metadata)
        super().__init__(name=name, metadata=node_metadata, **kwargs)

        # Converters should take one positional argument of any type, and can return anything!
        def capitalize_name(value: str) -> str:
            if not value:
                return value
            return value[0].upper() + value[1:]

        self.add_parameter(
            Parameter(
                name="first_name",
                input_types=["str"],
                type="str",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                output_type="str",
                default_value="Jane",
                tooltip="The first name of the user",
                # Converters allow you to modify the value set. You can add multiple converters, that will operate in order when a parameter value is set.
                converters=[capitalize_name],
                # If you don't specify allowed_modes, it defaults to all three modes being allowed (INPUT, OUTPUT, and PROPERTY)
            )
        )
        self.add_parameter(
            Parameter(
                name="last_name",
                output_type="str",
                type="str",
                default_value="Smith",
                tooltip="The last name of the user",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                converters=[capitalize_name],
            )
        )
        self.add_parameter(
            Parameter(
                name="full_name",
                output_type="str",
                tooltip="The full name of the user",
                allowed_modes={ParameterMode.OUTPUT},
            )
        )

    def process(self) -> None:
        # All of the current values of a parameter are stored on self.parameter_values (If they have an INPUT or PROPERTY)
        first_name = self.parameter_values["first_name"]
        last_name = self.parameter_values["last_name"]
        # All output values should be set in self.parameter_output_values.
        full_name = f"{first_name} {last_name}"
        self.parameter_output_values["full_name"] = full_name
        # The node is complete!
