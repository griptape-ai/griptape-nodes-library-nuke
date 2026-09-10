// Mirrors the public names in nuke_host_api/protocol.py.
const Protocol = (function () {
  const VERB = {
    CONNECT: "NukeConnectRequest",
    LIST_WORKFLOWS: "NukeListWorkflowsRequest",
    DESCRIBE_WORKFLOW: "NukeDescribeWorkflowRequest",
    LOAD_WORKFLOW: "NukeLoadWorkflowRequest",
    EXECUTE_WORKFLOW: "NukeExecuteWorkflowRequest",
    GET_EXECUTION_STATE: "NukeGetExecutionStateRequest",
    GET_PARAMETER_VALUES: "NukeGetParameterValuesRequest",
    SET_PARAMETER_VALUES: "NukeSetParameterValuesRequest",
    CANCEL_EXECUTION: "NukeCancelExecutionRequest",
    LIST_PROJECTS: "NukeListProjectsRequest",
    GET_CURRENT_PROJECT: "NukeGetCurrentProjectRequest",
    SET_CURRENT_PROJECT: "NukeSetCurrentProjectRequest",
    DESCRIBE_PROJECT: "NukeDescribeProjectRequest",
  };

  const NOTIFICATION = {
    NODE_STATE: "NukeNodeStateEvent",
    PARAMETER_VALUE: "NukeParameterValueEvent",
    EXECUTION_STATE: "NukeExecutionStateEvent",
    EXECUTION_NODES: "NukeExecutionNodesEvent",
  };

  const CLIENT_PROTOCOL_VERSIONS = [1];

  const TERMINAL_EXECUTION_STATES = ["completed", "failed", "cancelled"];
  const EXECUTION_STATES = TERMINAL_EXECUTION_STATES.concat(["running"]);
  const KNOWN_NODE_STATES = ["unresolved", "running", "resolved", "failed"];

  const KNOWN_VALUE_TYPES = [
    "GTImage",
    "GTMovie",
    "GTFile",
    "GTText",
    "GTNumber",
    "GTBool",
    "GTNull",
  ];
  // Types that carry no sources: the descriptor reports the type, not the value.
  const SCALAR_TYPES = ["GTText", "GTNumber", "GTBool", "GTNull"];
  const MEDIA_TYPES = ["GTImage", "GTMovie", "GTFile"];
  const PREVIEWABLE = { GTImage: "img", GTMovie: "video" };

  const USABLE_PROJECT_STATUSES = ["GOOD", "FLAWED"];
  const usableProject = (status) => USABLE_PROJECT_STATUSES.indexOf(status) !== -1;

  const isTerminal = (executionState) => TERMINAL_EXECUTION_STATES.indexOf(executionState) !== -1;
  const isScalar = (valueType) => SCALAR_TYPES.indexOf(valueType) !== -1;
  const isMedia = (valueType) => MEDIA_TYPES.indexOf(valueType) !== -1;

  return {
    VERB,
    NOTIFICATION,
    CLIENT_PROTOCOL_VERSIONS,
    TERMINAL_EXECUTION_STATES,
    EXECUTION_STATES,
    KNOWN_NODE_STATES,
    KNOWN_VALUE_TYPES,
    SCALAR_TYPES,
    MEDIA_TYPES,
    PREVIEWABLE,
    USABLE_PROJECT_STATUSES,
    usableProject,
    isTerminal,
    isScalar,
    isMedia,
  };
})();
