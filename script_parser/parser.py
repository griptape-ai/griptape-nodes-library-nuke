from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedNode:
    node_class: str
    knobs: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.knobs.get("name", "")


def parse_script(text: str) -> list[ParsedNode]:
    """Parse a .nk script and return all non-Root top-level nodes.

    Limitation: brace counting does not account for braces inside quoted
    string values or TCL expressions, which may desync depth tracking on
    scripts with complex expressions. Sufficient for annotation discovery.
    """
    nodes: list[ParsedNode] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Skip blank lines, comments, version declaration
        if not stripped or stripped.startswith("#") or stripped.startswith("version "):
            i += 1
            continue

        # Top-level node opener: "Word {" or "Word.Word {"
        if stripped.endswith("{") and " " not in stripped[:-1].strip():
            node_class = stripped[:-1].strip()
            i += 1
            knobs: dict[str, str] = {}
            pending_user_knob: str | None = None
            depth = 1

            while i < n and depth > 0:
                raw = lines[i]
                inner = raw.strip()

                depth += inner.count("{") - inner.count("}")
                if depth <= 0:
                    i += 1
                    break

                # addUserKnob declaration — extract knob name, ignore tab groups (type 20)
                if inner.startswith("addUserKnob {"):
                    content = inner[len("addUserKnob {") :].rstrip("}")
                    tokens = content.split()
                    if tokens and tokens[0] != "20":
                        # tokens[0]=type, tokens[1]=knob_name
                        pending_user_knob = tokens[1] if len(tokens) > 1 else None
                    else:
                        pending_user_knob = None
                    i += 1
                    continue

                # Key-value line
                if " " in inner and not inner.startswith("{"):
                    key, _, rest = inner.partition(" ")
                    value = _unquote(rest.strip())

                    if pending_user_knob and key == pending_user_knob:
                        knobs[key] = value
                        pending_user_knob = None
                    elif key not in ("addUserKnob",):
                        knobs[key] = value

                i += 1

            if node_class != "Root":
                nodes.append(ParsedNode(node_class=node_class, knobs=knobs))
            continue

        i += 1

    return nodes


def _unquote(value: str) -> str:
    """Strip surrounding double-quotes from a string value if present."""
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        return value[1:-1]
    return value
