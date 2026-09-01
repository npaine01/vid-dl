# vid-dl

A tiny local web app for downloading YouTube videos and audio, built on top of [yt-dlp](https://github.com/yt-dlp/yt-dlp). Paste a link, pick a format, click Download — no terminal commands to type.

## Disclaimer

This project is **not affiliated with, endorsed by, or connected to YouTube or Google** in any way.

It is a personal-use automation tool that installs and drives a local copy of the open-source `yt-dlp` project. Downloading video you don't have the rights to may violate YouTube's Terms of Service and/or copyright law, depending on your jurisdiction and how you use the content. **You are responsible for how you use this tool** — only download content you own, have permission to use, or that is otherwise licensed for download (e.g. Creative Commons, public domain, or your own uploads).

This repository does **not** include or redistribute yt-dlp itself. It is downloaded directly from [PyPI](https://pypi.org/project/yt-dlp/) the first time you run the launcher, under yt-dlp's own license (The Unlicense), and is kept up to date automatically on every subsequent run.

## Features

- Video (MP4) or audio-only (MP3) downloads
- Quality picker: Best, 4K, 2K, 1080p (default), 720p, 480p
- Optional English subtitles (`.srt`), with automatic fallback to auto-generated captions if no human-made ones exist
- Live progress bar with total file size
- Plain browser UI — no command line typing after setup
- Checks for and installs yt-dlp updates automatically on every launch

## Requirements

- **macOS** with **Python 3** (already included on modern macOS; otherwise install from [python.org](https://www.python.org/downloads/))
- **[ffmpeg](https://ffmpeg.org)** — optional but recommended. Needed for MP3 extraction and for merging separate video/audio streams into the best-quality MP4. Without it, video quality is capped to formats that don't require merging, and MP3 downloads won't work.

  Get [Homebrew](https://brew.sh) first if you don't have it, then pick one:

  ```bash
  brew install ffmpeg        # downloads, MP3, merging
  brew install ffmpeg-full   # the above, plus burning subtitles into video
  ```

  **Why two options.** Homebrew's `ffmpeg` formula no longer includes libass,
  the library that draws subtitles into the picture, so it cannot burn
  subtitles. `ffmpeg-full` can. It is also *keg-only*, meaning Homebrew
  deliberately keeps it off your `PATH` — this app looks for it in its install
  location, so you don't have to do anything, but be aware that typing
  `ffmpeg` in Terminal won't find it.

  **If you install both, keep them updated together** (`brew upgrade`).
  Installing one upgrades shared libraries the other may still be linked
  against, which can leave the older copy unable to start at all. This app
  runs each candidate before trusting it, so it will pass over a broken one
  rather than failing mysteriously.
- **yt-dlp** — installed automatically the first time you run the app. You don't need to install it yourself.

## Installation

1. Clone or download this repository:

   ```bash
   git clone https://github.com/jpasden/vid-dl.git
   ```

2. Open the folder in Finder.
3. Double-click **`Start YouTube Downloader.command`**.
   - The first time, macOS may warn that it's from an unidentified developer. Right-click the file → **Open**, then confirm, to bypass this once.
   - The launcher installs `yt-dlp` automatically if it isn't already present, and checks for updates every time you run it afterward.

## Usage

1. Running the launcher opens a page in your browser at `http://127.0.0.1:8642`.
2. Paste a YouTube video URL.
3. Choose **Video (MP4)** or **Audio only (MP3)**.
4. Pick a max quality (1080p by default).
5. Leave **"Download English subtitles"** checked if you want a `.srt` file saved alongside the video.
6. Click **Download** and watch the progress bar (shows percent complete and total file size).
7. Files are saved to `~/Downloads/YT` by default — click **"Open downloads folder"** to jump there.
8. When you're done, close the Terminal window (or press `Ctrl+C` in it) to stop the app.

## Repairing auto-generated captions

YouTube's automatic captions imitate broadcast rolling captions. Downloaded as
SRT, that scrolling is baked in as duplicated text: every line is written three
times, and a subtitle you have already heard sits on screen over the audio of
the next one. Roughly half of every such file is 10-millisecond scroll frames.

`subs.py` repairs this. It works on its own, on any folder of subtitle files,
independently of the rest of the app:

```bash
python3 subs.py                      # every .srt/.vtt in the current folder
python3 subs.py clip.srt             # one file
python3 subs.py --glossary terms.txt # also apply corrections
```

Repaired files are written alongside the originals with a `_CLEAN` suffix.
Nothing is overwritten. Human-authored captions are detected and left alone —
the check is structural, so it holds for any language.

Speech recognition also mistranscribes proper nouns, place names and technical
vocabulary, which repairing the format does not fix. The optional glossary
applies literal corrections you supply:

```
# terms.txt — one substitution per line
been along = Bennelong
gagal = Gadigal
```

It reports how many times each entry matched, and warns about entries that
matched nothing — which usually means the source spells the term differently
than you assumed. It applies exactly what you give it and infers nothing;
deciding the correct spellings is your job, ideally against whatever source
the video was scripted from.

## How it works

Standard library only, no dependencies beyond `yt-dlp` itself:

| File | Role |
|---|---|
| `server.py` | Local web server: routing and static files |
| `ytdlp.py` | yt-dlp command construction and output parsing |
| `jobs.py` | Job state and download execution |
| `media.py` | Locating a usable ffmpeg |
| `subs.py` | Caption repair and correction glossary |
| `index.html` / `style.css` / `app.js` | Front end |

Everything runs locally on your machine — no data is sent anywhere except to
YouTube itself to fetch the video you asked for.

Run the tests with:

```bash
python3 -m unittest discover -s tests
```

## License

The wrapper/UI code in this repository is licensed under the MIT License — see [LICENSE](LICENSE).

`yt-dlp`, which this tool installs and calls at runtime, is licensed separately under [The Unlicense](https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE) and is not included in this repository.
