"""Points an annotated Read node at an input file, shared by runner.py and baker.py.

Stdlib only — runs inside Nuke's bundled interpreter.
"""

from __future__ import annotations


def set_input_file(node: object, path: str, first: object, last: object) -> None:
    """Point a Read node at `path`, carrying a sequence range across when there is one."""
    knob = node["file"]  # type: ignore[index]
    # fromUserText runs the same callbacks as editing the knob by hand, which set
    # first/last/origfirst/origlast/origset together. setValue sets the path alone and
    # leaves whatever range the .nk was saved with. Deliberately not nuke.getFileNameList:
    # the engine already scanned this sequence, and a second scan could disagree with it.
    # The range is split from the path on whitespace, so a path holding a space is
    # ambiguous and takes the explicit-knob branch instead.
    if first is not None and last is not None and hasattr(knob, "fromUserText") and " " not in path:
        knob.fromUserText(f"{path} {first}-{last}")
        return

    knob.setValue(path)
    if first is None or last is None:
        return
    # origfirst/origlast matter as well as first/last: Nuke treats them as the range the
    # file itself declares. origset stays unset here -- only fromUserText can set it.
    for knob_name, frame in (("first", first), ("last", last), ("origfirst", first), ("origlast", last)):
        if node.knob(knob_name) is not None:  # type: ignore[attr-defined]
            node[knob_name].setValue(frame)  # type: ignore[index]
