"""yt-dlp command construction and output parsing.

Pure functions: nothing here runs a subprocess, touches the filesystem, or
reads global configuration. Callers pass in what they know.
"""
import os
import re
import sys

DEFAULT_QUALITY = "1080"
VALID_QUALITIES = ("best", "2160", "1440", "1080", "720", "480")

PERCENT_RE = re.compile(r"\[download\]\s+([\d.]+)%")
SIZE_RE = re.compile(
    r"\[download\]\s+[\d.]+%\s+of\s+~?\s*([\d.]+\s?\S+?)(?:\s+at\s|\s+in\s|\s*$)")
DEST_RE = re.compile(r"Destination:\s*\"?([^\"\n]+?)\"?$")
MERGE_RE = re.compile(r"Merging formats into\s*\"?([^\"\n]+?)\"?$")
EXISTING_RE = re.compile(r"\[download\]\s+(.+?) has already been downloaded")

# Sidecars, not the media file the user asked for.
SUBTITLE_SUFFIXES = (".vtt", ".srt", ".ass", ".ssa", ".lrc", ".ttml", ".json3")
# Announced by post-processors, so the name is the finished article.
FINAL_MARKERS = ("[Merger]", "[ExtractAudio]", "[VideoConvertor]")


def video_format(quality, ffmpeg):
    """The -f expression for a maximum height, given ffmpeg availability.

    Without ffmpeg yt-dlp cannot merge separate video and audio streams, so
    only pre-merged formats are usable and quality is correspondingly lower.
    """
    cap = None if quality == "best" else quality
    if not ffmpeg:
        return f"best[height<={cap}]/b" if cap else "b"
    if cap:
        return f"bestvideo[height<={cap}]+bestaudio/best[height<={cap}]"
    return "bv*+ba/b"


def build_download_command(url, output_dir, mode="video",
                           quality=DEFAULT_QUALITY, sub_lang=None, ffmpeg=None):
    """Build the yt-dlp argv for one download.

    `ffmpeg` is the path to a working ffmpeg, or None. yt-dlp searches PATH on
    its own, which is not good enough: Homebrew's ffmpeg-full is keg-only and
    never on PATH, and a stale formula left on PATH may not run at all. So the
    location is always passed explicitly when we have one.
    """
    if quality not in VALID_QUALITIES:
        quality = DEFAULT_QUALITY

    command = [sys.executable, "-m", "yt_dlp", "--newline", "--no-playlist"]
    if ffmpeg:
        command += ["--ffmpeg-location", ffmpeg]

    if mode == "audio":
        command += ["-x", "--audio-format", "mp3"]
    else:
        command += ["-f", video_format(quality, ffmpeg),
                    "--merge-output-format", "mp4"]
        if sub_lang:
            # An exact language code, never a pattern: `en.*` matches both
            # `en` and `en-orig`, and yt-dlp then writes the same track twice.
            command += ["--write-subs", "--write-auto-subs",
                        "--sub-langs", sub_lang]
            if ffmpeg:
                command += ["--convert-subs", "srt"]

    command += ["-o", os.path.join(output_dir, "%(title)s.%(ext)s"), url]
    return command


def parse_progress(line):
    """Extract whatever progress information a yt-dlp output line carries."""
    update = {}
    percent = PERCENT_RE.search(line)
    if percent:
        update["percent"] = float(percent.group(1))
    size = SIZE_RE.search(line)
    if size:
        update["size"] = size.group(1).strip()
    merged = MERGE_RE.search(line)
    if merged:
        update["filename"] = os.path.basename(merged.group(1))
        update["final"] = True
        return update

    existing = EXISTING_RE.search(line)
    if existing:
        name = os.path.basename(existing.group(1))
        if not name.lower().endswith(SUBTITLE_SUFFIXES):
            update["filename"] = name
            update["final"] = True
        return update

    destination = DEST_RE.search(line)
    if destination:
        name = os.path.basename(destination.group(1))
        if not name.lower().endswith(SUBTITLE_SUFFIXES):
            update["filename"] = name
            update["final"] = line.startswith(FINAL_MARKERS)
    return update
