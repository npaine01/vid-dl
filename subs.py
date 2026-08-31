"""Caption repair for rolling-ASR subtitle files.

Standard library only, no platform dependencies, no assumptions about
language or source. Usable as a module or from the command line.
"""
import re

TAG_RE = re.compile(r"<[^>]*>")

TIMING_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


class Cue:
    __slots__ = ("start", "end", "lines")

    def __init__(self, start, end, lines):
        self.start = start
        self.end = end
        self.lines = lines

    def __repr__(self):
        return f"Cue({self.start}, {self.end}, {self.lines!r})"


def _ms(hours, minutes, seconds, fraction):
    return (int(hours) * 3600000 + int(minutes) * 60000
            + int(seconds) * 1000 + int(fraction.ljust(3, "0")))


def parse(text):
    """Parse SRT or VTT text into a list of Cue objects.

    Cues are located by scanning for timing lines rather than by splitting on
    blank lines. Rolling captions carry two line slots, and an empty top slot
    appears as a literal blank line *inside* a cue -- splitting on blank lines
    tears such a cue apart and silently discards its text.
    """
    lines = text.replace("\r\n", "\n").replace("﻿", "").split("\n")
    timing_at = [i for i, ln in enumerate(lines) if TIMING_RE.search(ln)]

    cues = []
    for n, i in enumerate(timing_at):
        groups = TIMING_RE.search(lines[i]).groups()
        stop = timing_at[n + 1] if n + 1 < len(timing_at) else len(lines)
        body = lines[i + 1:stop]

        while body and not body[-1].strip():
            body.pop()
        # The trailing number belongs to the next cue, not this one.
        if n + 1 < len(timing_at) and body and body[-1].strip().isdigit():
            body.pop()
            while body and not body[-1].strip():
                body.pop()

        cues.append(Cue(
            _ms(*groups[:4]),
            _ms(*groups[4:]),
            [t for t in (TAG_RE.sub("", ln).strip() for ln in body) if t],
        ))
    return cues


def _timestamp(value):
    hours, value = divmod(value, 3600000)
    minutes, value = divmod(value, 60000)
    seconds, millis = divmod(value, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def to_srt(cues):
    """Serialize cues as numbered SRT text."""
    return "\n".join(
        f"{number}\n{_timestamp(cue.start)} --> {_timestamp(cue.end)}\n"
        + "\n".join(cue.lines) + "\n"
        for number, cue in enumerate(cues, 1)
    )


BRIDGE_MS = 50
MIN_CUES_TO_JUDGE = 8
BRIDGE_RATIO = 0.2
DUPLICATE_RATIO = 0.25


def is_rolling(cues):
    """True if `cues` look like a rolling-ASR file rather than authored captions.

    Gates on structure only -- bridge-cue density and line duplication -- so it
    holds for any language and any producer of rolling captions. Authored
    captions score far below both thresholds and are left untouched.
    """
    if len(cues) < MIN_CUES_TO_JUDGE:
        return False
    bridges = sum(1 for cue in cues if cue.end - cue.start <= BRIDGE_MS)
    every_line = [line for cue in cues for line in cue.lines]
    if not every_line:
        return False
    duplication = 1 - len(set(every_line)) / len(every_line)
    return (bridges / len(cues) > BRIDGE_RATIO
            and duplication > DUPLICATE_RATIO)


MIN_CUE_MS = 400


def repair(cues):
    """Repair rolling-ASR duplication, or return `cues` unchanged if authored.

    Three rules. Keep only the newest line of each cue -- in a rolling display
    the last slot holds the speech actually being spoken, and the slots above
    it are leftovers from earlier cues. Skip a cue whose newest line repeats
    the one before it, which removes the scroll frames. Then let each surviving
    line run until the next one begins, reconstructing the true display window.

    No line is ever discarded. A window left shorter than MIN_CUE_MS is kept
    and reported by `short_cues` rather than dropped -- silently discarding
    short residue is how the opening line of a file goes missing.
    """
    if not is_rolling(cues):
        return cues

    spoken, previous = [], None
    for cue in cues:
        if not cue.lines:
            continue
        newest = cue.lines[-1]
        if newest == previous:
            continue
        spoken.append((newest, cue.start))
        previous = newest

    repaired = []
    for index, (line, start) in enumerate(spoken):
        if index + 1 < len(spoken):
            end = spoken[index + 1][1]
        else:
            end = max(cues[-1].end, start + MIN_CUE_MS)
        repaired.append(Cue(start, end, [line]))
    return repaired


def short_cues(cues):
    """Cues left below the readable floor. Empty for a healthy repair."""
    return [cue for cue in cues if cue.end - cue.start < MIN_CUE_MS]


# Scripts that do not delimit words with spaces. Anchoring a match to a word
# boundary in these never fires, because neighbouring characters are word
# characters too -- so boundary anchoring is decided per edge, not per glossary.
UNSPACED_RANGES = (
    (0x2E80, 0x2FFF),    # CJK radicals and Kangxi
    (0x3040, 0x30FF),    # Hiragana, Katakana
    (0x3400, 0x4DBF),    # CJK Extension A
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0xAC00, 0xD7AF),    # Hangul syllables
    (0x0E00, 0x0E7F),    # Thai
)


def _unspaced(character):
    point = ord(character)
    return any(low <= point <= high for low, high in UNSPACED_RANGES)


def _anchored(term):
    """Build a pattern for `term`, anchoring only edges that can bear it."""
    pattern = re.escape(term)
    if term[:1].isalnum() and not _unspaced(term[0]):
        pattern = r"\b" + pattern
    if term[-1:].isalnum() and not _unspaced(term[-1]):
        pattern = pattern + r"\b"
    return re.compile(pattern)


def parse_glossary(text):
    """Read `wrong = right` lines into entries, longest term first.

    Longest-first matters: a short entry must not consume part of a phrase a
    longer entry would have matched.
    """
    entries = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        wrong, right = line.split("=", 1)
        wrong, right = wrong.strip(), right.strip()
        if wrong:
            entries.append((wrong, right))
    return sorted(entries, key=lambda entry: len(entry[0]), reverse=True)


def apply_glossary(cues, entries):
    """Apply literal substitutions. Returns (cues, report).

    The report carries a count for every entry, including zero, so that entries
    which never matched can be surfaced -- those mean the source spelled the
    term differently than the author assumed, which is otherwise invisible.
    """
    report = []
    corrected = [Cue(cue.start, cue.end, list(cue.lines)) for cue in cues]
    for wrong, right in entries:
        pattern, hits = _anchored(wrong), 0
        for cue in corrected:
            for index, line in enumerate(cue.lines):
                line, count = pattern.subn(right, line)
                if count:
                    cue.lines[index] = line
                    hits += count
        report.append((wrong, right, hits))
    return corrected, report


def unmatched(report):
    """Glossary terms that matched nothing."""
    return [wrong for wrong, _, hits in report if hits == 0]


SUFFIX = "_CLEAN"


def process(text, entries=()):
    """Repair `text` and apply `entries`. Returns (srt_text, stats)."""
    cues = parse(text)
    rolling = is_rolling(cues)
    repaired = repair(cues)
    corrected, report = apply_glossary(repaired, entries)
    return to_srt(corrected), {
        "rolling": rolling,
        "cues_in": len(cues),
        "cues_out": len(corrected),
        "glossary": report,
        "short": len(short_cues(corrected)),
    }


def _cli(argv):
    import argparse
    import glob
    import os

    parser = argparse.ArgumentParser(
        prog="subs.py",
        description="Repair rolling-ASR caption files and apply a correction "
                    "glossary. Leaves authored captions untouched.")
    parser.add_argument("paths", nargs="*",
                        help="subtitle files (default: every .srt/.vtt here)")
    parser.add_argument("--glossary", metavar="FILE",
                        help="'wrong = right' substitutions, one per line")
    parser.add_argument("--suffix", default=SUFFIX,
                        help=f"output suffix (default: {SUFFIX})")
    args = parser.parse_args(argv)

    entries = []
    if args.glossary:
        try:
            with open(args.glossary, encoding="utf-8-sig") as handle:
                entries = parse_glossary(handle.read())
        except OSError as error:
            print(f"cannot read glossary {args.glossary}: {error}")
            return 1

    paths = args.paths or sorted(
        path for path in glob.glob("*.srt") + glob.glob("*.vtt")
        if not os.path.splitext(path)[0].endswith(args.suffix))
    if not paths:
        print("no subtitle files found")
        return 1

    failures = 0
    hits_by_term = {wrong: 0 for wrong, _ in entries}

    for path in paths:
        try:
            with open(path, encoding="utf-8-sig") as handle:
                source = handle.read()
        except OSError as error:
            print(f"{path}: cannot read ({error})")
            failures += 1
            continue

        output, stats = process(source, entries)
        for wrong, right, hits in stats["glossary"]:
            hits_by_term[wrong] += hits
        replaced = sum(hits for _, _, hits in stats["glossary"])

        if not stats["rolling"] and not replaced:
            print(f"{path}: no change (not a rolling-caption file)")
            continue

        destination = os.path.splitext(path)[0] + args.suffix + ".srt"
        with open(destination, "w", encoding="utf-8") as handle:
            handle.write(output)

        summary = f"{path}: {stats['cues_in']} -> {stats['cues_out']} cues"
        if replaced:
            summary += f", {replaced} replacements"
        if stats["short"]:
            summary += f", {stats['short']} cues under {MIN_CUE_MS}ms"
        print(f"{summary}  ->  {destination}")
        for wrong, right, hits in stats["glossary"]:
            if hits:
                print(f"    {wrong} -> {right} ({hits})")

    never_matched = [wrong for wrong, hits in hits_by_term.items() if hits == 0]
    if never_matched:
        print("\nglossary entries that matched nothing "
              "(the source may spell them differently):")
        for wrong in never_matched:
            print(f"    {wrong}")

    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
