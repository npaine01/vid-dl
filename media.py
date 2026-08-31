"""Locating and interrogating ffmpeg.

Homebrew's core `ffmpeg` formula no longer depends on libass, freetype or
fontconfig, so a stock install cannot burn subtitles. The capable formula is
`ffmpeg-full`, which is keg-only -- it installs outside PATH and
`shutil.which` will never see it. Hence an explicit search of known locations
before falling back to PATH.
"""
import os
import shutil

# Keg-only installs first: ffmpeg-full is a superset of the slim formula, so
# when both are present it is the better choice for every operation.
SEARCH_PATHS = (
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
)


def find_ffmpeg(search_paths=SEARCH_PATHS, which=shutil.which):
    """Return the path to the most capable ffmpeg available, or None."""
    for path in search_paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return which("ffmpeg")
