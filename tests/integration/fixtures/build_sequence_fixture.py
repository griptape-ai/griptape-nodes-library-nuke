"""Builds the sequence-input integration fixture. Runs inside `nuke -t`.

Writes a 5-frame PNG sequence whose every frame differs, then saves a .nk holding a
Read pointed at that sequence with a deliberately narrow authored range (1-1) and a
Write fed from it. A runner that fails to widen the Read's range renders frame 1
five times, which is what the test detects.

Stdlib + nuke only.
"""

from __future__ import annotations

import argparse
import sys

import nuke  # type: ignore[import-not-found]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--script-out", required=True)
    parser.add_argument("--last", type=int, default=5)
    args, _ = parser.parse_known_args()

    frames = f"{args.frames_dir}/plate.%04d.png".replace("\\", "/")

    nuke.scriptClear()
    constant = nuke.nodes.Constant(name="GenSource")
    # Each frame a different grey, so identical output frames prove the Read never
    # advanced past its authored last frame.
    constant["color"].setExpression("frame / 10.0")
    gen_write = nuke.nodes.Write(name="GenWrite", file=frames, file_type="png")
    gen_write.setInput(0, constant)
    nuke.execute(gen_write, 1, args.last)

    nuke.scriptClear()
    read = nuke.nodes.Read(name="ReadPlate")
    # fromUserText with a 1-1 range is how a .nk comes to hold a stale authored range.
    read["file"].fromUserText(f"{frames} 1-1")
    write = nuke.nodes.Write(name="WriteOut", file=f"{args.frames_dir}/out.%04d.png", file_type="png")
    write.setInput(0, read)
    nuke.scriptSaveAs(args.script_out, overwrite=1)

    print(f"OK {args.script_out}", file=sys.stderr)


main()
