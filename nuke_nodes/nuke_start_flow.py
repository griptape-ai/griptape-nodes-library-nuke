import logging
from typing import Any

from griptape_nodes.exe_types.node_types import StartNode
from griptape_nodes.exe_types.param_types.parameter_image import ParameterImage
from griptape_nodes.exe_types.param_types.parameter_string import ParameterString

logger = logging.getLogger(__name__)


class NukeStartFlow(StartNode):
    def __init__(
        self,
        name: str,
        metadata: dict[Any, Any] | None = None,
    ) -> None:
        if metadata is None:
            metadata = {}
        metadata["showaddparameter"] = True
        super().__init__(name, metadata)

        self.add_parameter(
            ParameterImage(
                name="input_image",
                default_value=None,
                tooltip="Input image",
            )
        )
        self.add_parameter(
            ParameterString(
                name="prompt",
                default_value=None,
                tooltip="Input text",
                multiline=True,
                placeholder_text="Enter your prompt to manipulate the image here...",
            )
        )

    def process(self) -> None:
        pass
