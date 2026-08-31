"""Synthetic caption fixtures.

Generates rolling-ASR files matching the structure measured in real YouTube
output, so tests never depend on third-party caption content. The measured
shape is: an opening cue showing the first line alone in the bottom slot,
then for each subsequent line a 10 ms bridge cue that scrolls the previous
line to the top slot, followed by a long cue pairing it with the new line.
That yields exactly 2n-1 cues for n lines.
"""


def _stamp(value):
    hours, value = divmod(value, 3600000)
    minutes, value = divmod(value, 60000)
    seconds, millis = divmod(value, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _block(number, start, end, slots):
    return (f"{number}\n{_stamp(start)} --> {_stamp(end)}\n"
            + "\n".join(slots) + "\n")


def rolling(lines, start=1760, hold=2000, bridge=10):
    """Build a rolling-ASR SRT string displaying `lines` in order."""
    blocks, clock, number = [], start, 1
    blocks.append(_block(number, clock, clock + hold, ["", lines[0]]))
    clock += hold
    for previous, current in zip(lines, lines[1:]):
        number += 1
        blocks.append(_block(number, clock, clock + bridge, [previous, " "]))
        clock += bridge
        number += 1
        blocks.append(_block(number, clock, clock + hold, [previous, current]))
        clock += hold
    return "\n".join(blocks)


def authored(lines, start=1000, hold=2500, gap=200):
    """Build a conventional human-authored SRT: one line per cue, no repeats."""
    blocks, clock = [], start
    for number, line in enumerate(lines, 1):
        blocks.append(_block(number, clock, clock + hold, [line]))
        clock += hold + gap
    return "\n".join(blocks)
