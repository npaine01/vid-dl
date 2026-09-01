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
