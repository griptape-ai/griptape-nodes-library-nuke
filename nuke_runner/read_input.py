"""Points annotated Read and Write nodes at their files, shared by runner.py and baker.py.

Stdlib only — runs inside Nuke's bundled interpreter.
"""

from __future__ import annotations

import re

# A path whose own tail already reads as a frame range, e.g. "/plates/shot 1-5". Nuke
# splits the trailing whitespace token off as the range, so appending another one would
# leave the path's own range behind as part of the filename.
_TRAILING_RANGE = re.compile(r".* \d+-\d+$")


def set_input_file(node: object, path: str, first: object, last: object) -> None:
    """Point a Read node at `path`, carrying a sequence range across when there is one."""
    knob = node["file"]  # type: ignore[index]
    # fromUserText runs the same callbacks as editing the knob by hand, which set
    # first/last/origfirst/origlast/origset together. setValue sets the path alone and
    # leaves whatever range the .nk was saved with. Deliberately not nuke.getFileNameList:
    # the engine already scanned this sequence, and a second scan could disagree with it.
    # Nuke splits only the final whitespace token off as the range, so an ordinary spaced
    # path like "/plates/My Show/bg.####.exr" round-trips fine -- verified against Nuke
    # 17.0v1. Only a path whose own tail already reads as a range is ambiguous.
    if first is not None and last is not None and hasattr(knob, "fromUserText") and not _TRAILING_RANGE.match(path):
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


def set_output_file(node: object, path: str) -> None:
    """Point a Write node at `path`, letting the destination extension pick the format."""
    node["file"].setValue(path)  # type: ignore[index]
    # file_type survives setValue and outranks the extension, so a comp authored as exr
    # writes EXR data into a .png destination and the frames will not open. Clearing the
    # knob to " " restores Nuke's infer-from-extension default -- but only when there is
    # an extension to infer from: with an extensionless destination the knob is the only
    # format signal and execute() fails outright.
    knob = node.knob("file_type")  # type: ignore[attr-defined]
    if knob is None:
        return
    tail = path.rsplit("/", 1)[-1]
    if "." in tail:
        knob.setValue(" ")
