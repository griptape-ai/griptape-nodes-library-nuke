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

  function valueItems(descriptor) {
    if (!descriptor || descriptor.value === null || descriptor.value === undefined) return [];
    return Array.isArray(descriptor.value) ? descriptor.value : [descriptor.value];
  }

  const itemText = (item) => (item && typeof item === "object" ? item.path : item);

  function fieldValueFrom(descriptor) {
    const items = valueItems(descriptor).filter((item) => item !== null && item !== undefined);
    if (!items.length) return undefined;
    return items.map((item) => String(itemText(item))).join(", ");
  }

  // Use value_type because unmapped artifact parameters may produce a different runtime type.
  function nukeNodePlan(descriptor) {
    if (!descriptor || typeof descriptor !== "object") return [];
    const valueType = descriptor.value_type || "?";
    if (isScalar(valueType)) return [{ note: "A scalar. It belongs on a knob, not in the DAG." }];

    const items = valueItems(descriptor);
    if (!items.length) return [{ note: "Unset. Nothing to create." }];

    return items.map((item) => {
      const path = item && item.path;
      if (!path) return { note: "An unset item. Nothing to create." };
      const padded = /#+/.test(path);
      return {
        call: padded
          ? 'nuke.nodes.Read(file="' + path + '", first=<first>, last=<last>)'
          : 'nuke.nodes.Read(file="' + path + '")',
        note: padded ? "Frame padding. The frame range is not in the descriptor: scan the directory or ask." : "A single file.",
        source: path,
      };
    });
  }

  return {
    paramKey,
    flattenValues,
    unflatten,
    valueItems,
    fieldValueFrom,
    nukeNodePlan,
  };
})();
