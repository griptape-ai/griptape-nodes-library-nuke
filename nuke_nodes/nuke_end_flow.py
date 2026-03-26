from typing import Any

from griptape_nodes.exe_types.node_types import EndNode
from griptape_nodes.exe_types.param_types.parameter_image import ParameterImage


class NukeEndFlow(EndNode):
    def __init__(
        self,
        name: str,
        metadata: dict[Any, Any] | None = None,
    ) -> None:
        if metadata is None:
            metadata = {}
        super().__init__(name, metadata)
        metadata["showaddparameter"] = True
        image_output_param = ParameterImage(
            name="output_image",
            default_value=None,
            tooltip="Output image",
        )
        self.add_parameter(image_output_param)
        self.move_element_up_down(image_output_param.name, up=True)

    def process(self) -> None:
        super().process()

    @classmethod
    def get_default_node_parameter_names(cls) -> list[str]:
        """Get the names of the parameters configured on the node by default."""
        # Execution Status Component parameters
        params = ["was_successful", "result_details"]
        # Control parameters
        params.extend(["exec_in", "failed"])
        return params
