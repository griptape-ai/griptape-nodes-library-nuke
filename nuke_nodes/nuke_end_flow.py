from __future__ import annotations

from typing import Any

from griptape.artifacts import UrlArtifact
from griptape_nodes.exe_types.node_types import EndNode, TrackedParameterOutputValues


class _NukeEndFlowTrackedParameterOutputValues(TrackedParameterOutputValues):
    """Output values dict that unwraps UrlArtifacts so their macros can be resolved."""

    def __setitem__(self, key: str, value: Any) -> None:
        # A str is handed to the base because that is the only shape whose macros get
        # resolved: the base __setitem__ recursively resolves macros (via
        # VariableResolver) into str/dict/list, returning anything else untouched. A
        # macro left inside an artifact would reach Nuke as a literal "{outputs}/..."
        # path. Only the UrlArtifact family is converted: str() on other artifacts
        # yields a description, or raises on binary.
        if isinstance(value, UrlArtifact):
            value = str(value)
        super().__setitem__(key, value)


class NukeEndFlow(EndNode):
    def __init__(
        self,
        name: str,
        metadata: dict[Any, Any] | None = None,
    ) -> None:
        if metadata is None:
            metadata = {}
        metadata["showaddparameter"] = True
        super().__init__(name, metadata)
        self.parameter_output_values = _NukeEndFlowTrackedParameterOutputValues(self)

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
