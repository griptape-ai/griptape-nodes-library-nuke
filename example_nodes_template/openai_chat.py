from typing import Any

import openai
from griptape.events import TextChunkEvent
from griptape.structures import Agent
from griptape.utils import Stream
from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import ControlNode


class OpenAIChat(ControlNode):
    def __init__(self, name: str, metadata: dict[str, Any] | None = None, **kwargs) -> None:
        node_metadata = {"category": "ControlNodes", "description": "An example node with dependencies"}
        if metadata:
            node_metadata.update(metadata)
        super().__init__(name=name, metadata=node_metadata, **kwargs)

        self.add_parameter(
            Parameter(
                name="prompt",
                input_types=["str"],
                type="str",
                default_value="Hey! What's up?",
                tooltip="The prompt to call an agent",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True},
            )
        )
        self.add_parameter(
            Parameter(
                name="output",
                output_type="str",
                tooltip="The output from the agent",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"multiline": True, "placeholder_text": "The agent response"},
            )
        )

    # This node makes a call to OpenAI, so it has a dependency. We have to define that method to properly catch it.
    def validate_before_node_run(self) -> list[Exception] | None:
        # All env values are stored in the SecretsManager. Check if they exist using this method.
        exceptions = []
        try:
            api_key = self.get_config_value(service="OpenAI", value="OPENAI_API_KEY")
        except Exception as e:
            # Add any exceptions to your list to return
            exceptions.append(e)
            return exceptions
        try:
            client = openai.OpenAI(api_key=api_key)
            client.models.list()
        except Exception as e:
            exceptions.append(e)
        # if there are exceptions, they will display when the user tries to run the flow with the node.
        return exceptions if exceptions else None

    def process(self) -> None:
        # All of the current values of a parameter are stored on self.parameter_values
        prompt = self.parameter_values["prompt"]
        # Use a griptape agent to run the structure!
        agent = Agent(stream=True)
        self.parameter_output_values["output"] = ""
        # Running with the Stream Util allows you to stream your responses to the node!
        for artifact in Stream(agent, event_types=[TextChunkEvent]).run(prompt):
            self.append_value_to_parameter("output", artifact.value)
