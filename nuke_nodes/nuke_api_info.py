"""Canvas-visible status node for the Nuke host API.

Surfaces the protocol version, the notification topic, and the value type set so they can
be read off the canvas when debugging a host connection, instead of being inferred from
logs.
"""

from __future__ import annotations

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import DataNode

from nuke_host_api.handlers import event_topic
from nuke_host_api.protocol import PROTOCOL_VERSION, VALUE_TYPES


class NukeApiInfo(DataNode):
    """Reports the host API surface this engine currently exposes."""

    def __init__(self, name: str, metadata: dict | None = None) -> None:
        super().__init__(name, metadata)
        self.add_parameter(
            Parameter(
                name="protocol_version",
                type="int",
                default_value=PROTOCOL_VERSION,
                tooltip="Host API protocol version this library build speaks.",
                allowed_modes={ParameterMode.PROPERTY, ParameterMode.OUTPUT},
            )
        )
        self.add_parameter(
            Parameter(
                name="event_topic",
                type="str",
                default_value="",
                tooltip="Topic a host must subscribe to for node and parameter notifications.",
                allowed_modes={ParameterMode.PROPERTY, ParameterMode.OUTPUT},
            )
        )
        self.add_parameter(
            Parameter(
                name="value_types",
                type="str",
                default_value=", ".join(VALUE_TYPES),
                tooltip="The closed value type set a host switches on.",
                allowed_modes={ParameterMode.PROPERTY, ParameterMode.OUTPUT},
            )
        )

    def process(self) -> None:
        self.parameter_output_values["protocol_version"] = PROTOCOL_VERSION
        self.parameter_output_values["event_topic"] = event_topic()
        self.parameter_output_values["value_types"] = ", ".join(VALUE_TYPES)
