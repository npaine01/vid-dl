#!/bin/bash
# Double-click this file to launch the YouTube Downloader.
# It installs/updates yt-dlp on every run and opens the app in your browser.

cd "$(dirname "$0")" || exit 1

echo "YouTube Downloader"
echo "-------------------"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 was not found on this Mac."
  echo "Install it from https://www.python.org/downloads/ and try again."
  read -p "Press Enter to close..."
  exit 1
fi

# --- Install or update yt-dlp (the actual downloader engine) ---
if ! python3 -c "import yt_dlp" >/dev/null 2>&1; then
  echo "Installing yt-dlp (one-time setup)..."
  python3 -m pip install --user -q yt-dlp || python3 -m pip install --user --break-system-packages -q yt-dlp
  if ! python3 -c "import yt_dlp" >/dev/null 2>&1; then
    echo "Could not install yt-dlp automatically."
    echo "Try running this manually in Terminal:"
    echo "  python3 -m pip install --user yt-dlp"
    read -p "Press Enter to close..."
    exit 1
  fi
  echo "yt-dlp installed."
else
  OLD_VERSION=$(python3 -m yt_dlp --version 2>/dev/null)
  echo "Checking for yt-dlp updates (currently $OLD_VERSION)..."
  python3 -m pip install --user -q --upgrade yt-dlp 2>/dev/null \
    || python3 -m pip install --user --break-system-packages -q --upgrade yt-dlp 2>/dev/null
  NEW_VERSION=$(python3 -m yt_dlp --version 2>/dev/null)
  if [ "$OLD_VERSION" != "$NEW_VERSION" ]; then
    echo "Updated yt-dlp: $OLD_VERSION -> $NEW_VERSION"
  else
    echo "yt-dlp is up to date ($NEW_VERSION)."
  fi
fi

# --- Check for ffmpeg (needed for MP4 merging, MP3, and subtitle burn-in) ---
# Uses the app's own detection: Homebrew's ffmpeg-full is keg-only, so it is
# never on PATH and `command -v ffmpeg` would miss a perfectly good install.
if ! python3 -c "import sys, media; sys.exit(0 if media.find_ffmpeg() else 1)" 2>/dev/null; then
  echo ""
  echo "NOTE: no working ffmpeg found."
  echo "  Without it: video downloads are capped at lower pre-merged quality,"
  echo "  and MP3 (audio-only) downloads won't work at all."
  echo ""
  echo "  If you don't have Homebrew yet, install it from https://brew.sh first."
  echo "  Then pick one:"
  echo "    brew install ffmpeg        # downloads, MP3, merging"
  echo "    brew install ffmpeg-full   # the above, plus burning subtitles into video"
  echo ""
  echo "  Nothing to place by hand - Homebrew handles it."
  echo ""
fi

echo ""
echo "Starting the downloader... your browser will open automatically."
echo "Keep this window open while you use it. Close it (or press Ctrl+C) to stop."
echo ""

python3 server.py
