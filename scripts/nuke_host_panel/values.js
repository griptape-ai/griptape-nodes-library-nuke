const Values = (function () {
  const { isScalar } = Protocol;

  const paramKey = (node, parameter) => node + "." + parameter;

  // Convert the nested wire shape to keys used by panel state.
  function flattenValues(byNode, live) {
    const flat = {};
    Object.keys(byNode || {}).forEach((node) => {
      const parameters = byNode[node] || {};
      Object.keys(parameters).forEach((parameter) => {
        flat[paramKey(node, parameter)] = { value: parameters[parameter], live: Boolean(live) };
      });
    });
    return flat;
  }

  function unflatten(flat) {
    const byNode = {};
    Object.keys(flat || {}).forEach((key) => {
      const cut = key.indexOf(".");
      if (cut === -1) return;
      const node = key.slice(0, cut);
      if (!byNode[node]) byNode[node] = {};
      byNode[node][key.slice(cut + 1)] = (flat[key] || {}).value;
    });
    return byNode;
  }

  // Prefer a source locator; scalars carry no source, so fall back to the descriptor's value.
  function fieldValueFrom(descriptor) {
    if (!descriptor || typeof descriptor !== "object") return undefined;
    const sources = Array.isArray(descriptor.sources) ? descriptor.sources : [];
    const first = sources.length ? sources[0] || {} : null;
    if (first && first.kind !== "inline" && first.value) return first.value;
    if (descriptor.value !== null && descriptor.value !== undefined) {
      return String(descriptor.value);
    }
    return undefined;
  }

  // Use value_type because unmapped artifact parameters may produce a different runtime type.
  function nukeNodePlan(descriptor) {
    if (!descriptor || typeof descriptor !== "object") return [];
    const valueType = descriptor.value_type || "?";
    const sources = Array.isArray(descriptor.sources) ? descriptor.sources : [];

    if (valueType === "GTNull") return [{ note: "Unset. Nothing to create." }];
    if (isScalar(valueType)) return [{ note: "A scalar. It belongs on a knob, not in the DAG." }];
    if (!sources.length) {
      return [
        {
          note:
            valueType +
            " with no sources should not happen: a value pointing at no bytes is reported as GTText. " +
            "Treat it as unavailable rather than creating an empty Read.",
        },
      ];
    }

    return sources.map((source) => {
      const kind = source.kind || "?";
      if (kind === "macro") {
        return { note: "An unresolved template. A configuration error, not a file to read." };
      }
      if (kind === "inline") {
        return { note: "No locator. Read the url or path form of the same value." };
      }
      if (kind === "url") {
        return {
          call: 'nuke.nodes.Read(file="<localized>")',
          note: "This layer moves no bytes, and a Read node cannot take an http path: fetch it first.",
          source: source.value || "",
        };
      }
      if (kind === "path") {
        return {
          call: source.is_pattern
            ? 'nuke.nodes.Read(file="' + (source.value || "") + '", first=<first>, last=<last>)'
            : 'nuke.nodes.Read(file="' + (source.value || "") + '")',
          note: source.is_pattern
            ? "The frame range is not in the descriptor: scan the directory or ask."
            : "A single frame.",
          source: source.value || "",
        };
      }
      return { note: "Unrecognized source kind. Never fatal: a new kind costs a version bump." };
    });
  }

  return {
    paramKey,
    flattenValues,
    unflatten,
    fieldValueFrom,
    nukeNodePlan,
  };
})();
