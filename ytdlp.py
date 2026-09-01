"""yt-dlp command construction, output parsing, and execution helpers.

Command building and parsing are pure -- callers pass in what they know. The
few helpers at the end that actually invoke yt-dlp take an injectable runner
so they can be tested without touching the network.
"""
import concurrent.futures
import json
import os
import re
import subprocess
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
    # Prefer m4a (AAC) audio: yt-dlp's plain `bestaudio` picks Opus on
    # YouTube, and QuickTime cannot play Opus in an MP4 at all.
    if cap:
        return (f"bestvideo[height<={cap}]+bestaudio[ext=m4a]/"
                f"bestvideo[height<={cap}]+bestaudio/best[height<={cap}]")
    return "bv*+ba[ext=m4a]/bv*+ba/b"


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


WATCH_URL = "https://www.youtube.com/watch?v="

# Languages the app offers. YouTube machine-translates its automatic captions
# into ~157 languages; listing them all would bury the few that are real.
OFFERED_LANGUAGES = ("en", "ja", "zh-Hans", "zh-Hant", "it", "es", "ko")

KIND_ORDER = {"captions": 0, "original": 1, "translated": 2}


def build_resolve_command(url):
    """List a playlist's contents without fetching any of them."""
    return [sys.executable, "-m", "yt_dlp", "--flat-playlist",
            "--dump-single-json", "--no-warnings", url]


def build_probe_command(url):
    """Fetch one video's metadata, including which subtitle tracks exist."""
    return [sys.executable, "-m", "yt_dlp", "--dump-single-json",
            "--no-playlist", "--skip-download", "--no-warnings", url]


def parse_resolution(info):
    """Normalise a resolve response into {kind, title, items}."""
    if info.get("_type") == "playlist" or "entries" in info:
        entries = info.get("entries") or []
        items = [_item(entry) for entry in entries if entry]
        return {"kind": "playlist", "title": info.get("title") or "Playlist",
                "items": [item for item in items if item]}
    item = _item(info)
    return {"kind": "video", "title": info.get("title") or "",
            "items": [item] if item else []}


def _item(entry):
    identifier = entry.get("id")
    url = entry.get("url") or entry.get("webpage_url")
    if not url and identifier:
        url = WATCH_URL + identifier
    if not url:
        return None
    return {"id": identifier, "url": url,
            "title": entry.get("title") or url,
            "duration": entry.get("duration")}


def parse_subtitle_tracks(info):
    """The subtitle tracks worth offering for one video.

    Three kinds, and the difference matters. Human-authored captions are
    authoritative. The automatic track in the video's own language is speech
    recognition -- imperfect, especially on names. Everything else YouTube
    lists is a machine translation *of that recognition*, so it carries both
    sets of errors.
    """
    authored = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    source = _source_languages(info.get("language"), automatic)

    tracks, seen = [], set()

    for code, formats in sorted(authored.items()):
        if code.endswith("-orig") or code in seen:
            continue
        seen.add(code)
        tracks.append({"code": code, "name": _name(formats, code),
                       "kind": "captions"})

    for code, formats in sorted(automatic.items()):
        base = code[:-5] if code.endswith("-orig") else code
        if base in seen:
            continue
        is_source = base.lower() in source
        if not is_source and base not in OFFERED_LANGUAGES:
            continue
        seen.add(base)
        tracks.append({"code": base, "name": _name(formats, base),
                       "kind": "original" if is_source else "translated"})

    tracks.sort(key=lambda track: (KIND_ORDER[track["kind"]], track["code"]))
    return tracks


def _source_languages(declared, automatic):
    """Codes that identify the video's own language rather than a translation.

    `language` is often regional ('en-US') while the track is plain ('en'), and
    it is sometimes absent entirely -- but YouTube marks the transcribed track
    with a `<code>-orig` key, which is the more dependable signal. Only the
    primary subtag is added, never a broader prefix match, so a Simplified
    Chinese source does not make Traditional Chinese look original.
    """
    codes = set()
    for key in automatic:
        if key.endswith("-orig"):
            codes.add(key[:-5].lower())
    if declared:
        declared = declared.lower()
        codes.add(declared)
        codes.add(declared.split("-")[0])
    return codes


def _name(formats, code):
    for entry in formats or []:
        if entry.get("name"):
            return entry["name"].replace(" (Original)", "")
    return code


def merge_tracks(per_video):
    """Combine per-video track lists, counting how many offer each language."""
    total = len(per_video)
    if not total:
        return []

    counts, details = {}, {}
    for tracks in per_video:
        for track in tracks:
            counts[track["code"]] = counts.get(track["code"], 0) + 1
            details.setdefault(track["code"], track)

    merged = []
    for code, count in counts.items():
        track = dict(details[code])
        track["count"] = count
        track["total"] = total
        merged.append(track)

    # Languages every video has come first; then real captions before
    # machine translations.
    merged.sort(key=lambda track: (track["count"] < total,
                                   KIND_ORDER[track["kind"]], track["code"]))
    return merged


PROBE_WORKERS = 4


class ResolveError(Exception):
    """yt-dlp could not describe the URL."""


def _run_json(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    return result.stdout


def resolve(url, run=_run_json):
    """Describe `url`: a single video, or a playlist and its contents."""
    try:
        output = run(build_resolve_command(url))
    except (OSError, subprocess.SubprocessError) as error:
        raise ResolveError(f"Could not read that URL: {error}") from error

    if not (output or "").strip():
        raise ResolveError(
            "yt-dlp returned nothing for that URL. It may be private, "
            "region-locked, or not a video link.")
    try:
        return parse_resolution(json.loads(output))
    except json.JSONDecodeError as error:
        raise ResolveError("Could not understand yt-dlp's response.") from error


def probe_many(urls, run=_run_json, workers=PROBE_WORKERS):
    """Which subtitle languages the given videos offer, merged.

    One network round-trip per video, so this runs only over the videos
    actually selected, several at a time. A video that fails to probe is
    skipped rather than losing the whole batch.
    """
    if not urls:
        return []

    def probe(url):
        try:
            return parse_subtitle_tracks(json.loads(run(build_probe_command(url))))
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError,
                ValueError, TypeError):
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(probe, urls))
    return merge_tracks([tracks for tracks in results if tracks is not None])
