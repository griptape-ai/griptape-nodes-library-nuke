from typing import Any

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import DataNode
from griptape_nodes.traits.clamp import Clamp
from griptape_nodes.traits.minmax import MinMax


class Age(DataNode):
    def __init__(self, name: str, metadata: dict[str, Any] | None = None, **kwargs) -> None:
        node_metadata = {"category": "DataNodes", "description": "Age Node"}
        if metadata:
            node_metadata.update(metadata)
        super().__init__(name=name, metadata=node_metadata, **kwargs)

        self.add_parameter(
            Parameter(
                name="age",
                input_types=["int", "float"],
                type="int",
                output_type="int",
                default_value=30,
                tooltip="What is your age",
                allowed_modes={ParameterMode.PROPERTY, ParameterMode.OUTPUT},
                # Traits are classes that you can assign to a parameter
                # Clamp prevents the parameter values from being set outside of that range, and MinMax raises an error if that is attempted.
                # You can create your own traits as long as they inherit Trait from griptape_nodes.exe_types.core_types
                traits={MinMax(min_val=1, max_val=98), Clamp(min_val=1, max_val=98)},
                ui_options={"slider": {"min_val": 1, "max_val": 98}},
            )
        )

    def process(self) -> None:
        # All of the current values of a parameter are stored on self.parameter_values (If they have an INPUT or PROPERTY)
        age = self.parameter_values["age"]
        # All output values should be set in self.parameter_output_values.
        self.parameter_output_values["age"] = age
        # The node is complete!
