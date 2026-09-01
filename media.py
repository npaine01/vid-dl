"""Locating and interrogating ffmpeg.

Two hazards drive the design here.

Homebrew's core `ffmpeg` formula no longer depends on libass, freetype or
fontconfig, so a stock install cannot burn subtitles. The capable formula is
`ffmpeg-full`, which is keg-only -- it installs outside PATH, and
`shutil.which` will never see it. Hence an explicit search of known locations.

Separately, a binary that exists and is marked executable can still fail to
run: installing one formula upgrades shared libraries that an older formula's
binary still links against, leaving a dyld failure behind. Existence is
therefore not evidence of usability, and every candidate is executed once.
"""
import os
import re
import shutil
import subprocess

# Keg-only installs first: ffmpeg-full is a superset of the slim formula, so
# when both are present it is the better choice for every operation.
SEARCH_PATHS = (
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
)


def runs(path, args=("-version",), expect="ffmpeg version", timeout=10):
    """True if `path` actually executes and identifies itself."""
    try:
        result = subprocess.run([path, *args], capture_output=True, text=True,
                                timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and expect in (result.stdout or "")


def find_ffmpeg(search_paths=SEARCH_PATHS, which=shutil.which, verify=runs):
    """Return the path to the most capable *working* ffmpeg, or None."""
    candidates = list(search_paths)
    on_path = which("ffmpeg")
    if on_path:
        candidates.append(on_path)

    for path in candidates:
        if not (os.path.isfile(path) and os.access(path, os.X_OK)):
            continue
        if verify(path):
            return path
    return None


# --- burning ---------------------------------------------------------------

# Matches a filter listing row whose name field is exactly "subtitles".
SUBTITLE_FILTER_RE = re.compile(r"^\s*\S+\s+subtitles\s", re.MULTILINE)


def _filters(path):
    result = subprocess.run([path, "-hide_banner", "-filters"],
                            capture_output=True, text=True, timeout=15)
    return result.stdout or ""


def can_burn(path, run=_filters):
    """True if this ffmpeg can render subtitles into the picture.

    Homebrew's core `ffmpeg` formula no longer depends on libass, so the
    `subtitles` filter is simply absent and any burn attempt fails with
    "No such filter". `ffmpeg-full` carries it.
    """
    if not path:
        return False
    try:
        listing = run(path)
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(SUBTITLE_FILTER_RE.search(listing))


# libass picks fonts by family name through fontconfig. The usual defaults
# carry no CJK glyphs at all and render tofu boxes without any error, so the
# font is chosen from the subtitle language rather than left to chance.
LATIN_FONT = "Helvetica Neue"
FONTS = {
    "ja": "Hiragino Sans",
    "ko": "Apple SD Gothic Neo",
    "zh": "PingFang SC",
    "zh-hans": "PingFang SC",
    "zh-cn": "PingFang SC",
    "zh-sg": "PingFang SC",
    "zh-hant": "PingFang TC",
    "zh-tw": "PingFang TC",
    "zh-hk": "PingFang TC",
    "zh-mo": "PingFang TC",
}

# ASS FontSize against libass's script resolution. Measured on 1080p frames:
# 24 fits a 43-character line on one row, 30 wraps it to two.
SIZES = {"small": 18, "medium": 24, "large": 30}


def font_for(language):
    """The font family to render `language` with."""
    if not language:
        return LATIN_FONT
    code = language.lower().replace("_", "-")
    for suffix in ("-orig", "-auto"):
        if code.endswith(suffix):
            code = code[: -len(suffix)]
    if code in FONTS:
        return FONTS[code]
    return FONTS.get(code.split("-")[0], LATIN_FONT)


def font_size(name):
    return SIZES.get((name or "").lower(), SIZES["medium"])


def _fc_match(name):
    result = subprocess.run(["fc-match", name], capture_output=True,
                            text=True, timeout=10)
    return result.stdout or ""


def font_available(name, match=_fc_match):
    """Whether fontconfig resolves `name` to the family actually requested.

    fc-match never fails: asked for something absent it returns LastResort. So
    the answer is in the returned family name, not the exit status. When
    fontconfig itself is unavailable we assume yes and let ffmpeg decide,
    rather than blocking a burn that would have worked.
    """
    try:
        answer = match(name)
    except (OSError, subprocess.SubprocessError):
        return True
    return name.lower() in (answer or "").lower()


ENCODERS = {
    # Measured on 30s of 1080p30: libx264 4.2s, videotoolbox 3.3s. The gap is
    # small enough that a true quality target and hardware independence win.
    #
    # CRF 23, not 18. Burning re-encodes video that is already compressed, and
    # a near-lossless target spends most of its bitrate faithfully preserving
    # the source's own compression artefacts -- measured at 3.5x the source
    # size, turning a 275MB download into over a gigabyte.
    "libx264": ["-c:v", "libx264", "-crf", "23", "-preset", "medium"],
    "videotoolbox": ["-c:v", "h264_videotoolbox", "-q:v", "55"],
}
DEFAULT_ENCODER = "libx264"

# Quality alone does not bound the output, so the bitrate is also capped
# relative to the source. 1.5x leaves room for the subtitle overlay's sharp
# edges without preserving artefacts. Measured: 3.5x source down to 1.5x,
# with no visible difference.
BITRATE_HEADROOM = 1.5
MIN_BITRATE_KBPS = 500

OUT_TIME_RE = re.compile(r"^out_time=(\d+):(\d{2}):(\d{2})(?:\.(\d+))?")

# ISO 639-1 to the three-letter codes MP4 metadata expects.
ISO3 = {"en": "eng", "ja": "jpn", "zh": "chi", "ko": "kor", "it": "ita",
        "es": "spa", "fr": "fra", "de": "deu", "pt": "por", "ru": "rus"}


# Audio codecs MP4 can technically hold but common players cannot decode.
# QuickTime refuses Opus outright; VLC's MP4 demuxer often does too.
INCOMPATIBLE_AUDIO = ("opus", "vorbis")


def audio_arguments(codec):
    """Copy the audio unless it is a codec MP4 players choke on."""
    if codec and codec.lower() in INCOMPATIBLE_AUDIO:
        return ["-c:a", "aac", "-b:a", "128k"]
    return ["-c:a", "copy"]


def probe_bitrate(ffprobe, path, run=None):
    """Overall bitrate of `path` in bits per second, or None."""
    command = [ffprobe, "-v", "error", "-show_entries", "format=bit_rate",
               "-of", "default=nw=1:nk=1", path]
    try:
        output = run(command) if run else subprocess.run(
            command, capture_output=True, text=True, timeout=30).stdout
        return int((output or "").strip())
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None


def probe_audio_codec(ffprobe, path, run=None):
    """The audio codec of `path`, or None if it cannot be determined."""
    command = [ffprobe, "-v", "error", "-select_streams", "a:0",
               "-show_entries", "stream=codec_name",
               "-of", "default=nw=1:nk=1", path]
    try:
        output = run(command) if run else subprocess.run(
            command, capture_output=True, text=True, timeout=30).stdout
        return (output or "").strip().splitlines()[0].strip() or None
    except (OSError, subprocess.SubprocessError, IndexError, AttributeError):
        return None


def burn_command(ffmpeg, video, subtitle, output, font=LATIN_FONT,
                 size=SIZES["medium"], encoder=DEFAULT_ENCODER,
                 preview_seconds=None, preview_start=None, audio_codec=None,
                 source_bitrate=None):
    """Render `subtitle` permanently into `video`.

    `subtitle` must be a bare filename, with ffmpeg run from the directory
    holding it. The `subtitles=` filter parses its argument as a filtergraph,
    where a colon separates options and a comma separates filters -- both are
    ordinary characters in video titles. Copying the subtitle to a temporary
    directory under a safe name removes that entire class of failure rather
    than trying to escape it.
    """
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if preview_start:
        command += ["-ss", f"{preview_start / 1000:.3f}"]
    command += ["-i", video]
    if preview_seconds:
        command += ["-t", str(preview_seconds)]

    style = f"FontName={font},FontSize={size},Outline=2,Shadow=0"
    command += ["-vf", f"subtitles={subtitle}:force_style='{style}'"]
    command += ENCODERS.get(encoder, ENCODERS[DEFAULT_ENCODER])
    if source_bitrate:
        ceiling = max(MIN_BITRATE_KBPS,
                      int(source_bitrate * BITRATE_HEADROOM / 1000))
        command += ["-maxrate", f"{ceiling}k", "-bufsize", f"{ceiling * 2}k"]
    command += audio_arguments(audio_codec)
    command += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats",
                output]
    return command


def mux_command(ffmpeg, video, subtitle, output, language=None,
                audio_codec=None):
    """Embed `subtitle` as a switchable track. No video re-encoding."""
    code = ISO3.get((language or "").lower().split("-")[0], "und")
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-i", video, "-i", subtitle, "-c", "copy", "-c:s", "mov_text"]
    command += audio_arguments(audio_codec)
    command += ["-metadata:s:s:0", f"language={code}",
                "-movflags", "+faststart", output]
    return command


def parse_encode_progress(line, duration_ms):
    """Turn an ffmpeg -progress line into a percentage of `duration_ms`."""
    if not duration_ms:
        return {}
    match = OUT_TIME_RE.match(line.strip())
    if not match:
        return {}
    hours, minutes, seconds, fraction = match.groups()
    elapsed = (int(hours) * 3600000 + int(minutes) * 60000 + int(seconds) * 1000
               + int((fraction or "0")[:3].ljust(3, "0")))
    return {"percent": min(100.0, round(elapsed / duration_ms * 100, 1))}


def probe_duration(ffprobe, path, run=None):
    """Duration of `path` in milliseconds, or None if it cannot be determined."""
    command = [ffprobe, "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", path]
    try:
        output = run(command) if run else subprocess.run(
            command, capture_output=True, text=True, timeout=30).stdout
        return int(float(output.strip()) * 1000)
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None


def ffprobe_for(ffmpeg):
    """The ffprobe sitting beside a given ffmpeg."""
    if not ffmpeg:
        return None
    candidate = os.path.join(os.path.dirname(ffmpeg), "ffprobe")
    return candidate if os.path.isfile(candidate) else None
