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

# --- Check for ffmpeg (needed for best-quality MP4 merging and all MP3 downloads) ---
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo ""
  echo "NOTE: ffmpeg isn't installed."
  echo "  Without it: video downloads are capped at lower pre-merged quality,"
  echo "  and MP3 (audio-only) downloads won't work at all."
  echo ""
  echo "  You don't need to 'place' ffmpeg anywhere by hand - installing it with"
  echo "  Homebrew puts it on your PATH automatically. To install:"
  echo "    1. If you don't have Homebrew yet, install it from https://brew.sh"
  echo "       (run the command shown on that page in Terminal)"
  echo "    2. Then run:  brew install ffmpeg"
  echo "  That's it - no downloads to move, no folders to configure."
  echo ""
  echo "  (Alternative without Homebrew: download a static build from"
  echo "   https://evermeet.cx/ffmpeg/ and move the 'ffmpeg' binary into"
  echo "   /usr/local/bin so it's on your PATH.)"
  echo ""
fi

echo ""
echo "Starting the downloader... your browser will open automatically."
echo "Keep this window open while you use it. Close it (or press Ctrl+C) to stop."
echo ""

python3 server.py
