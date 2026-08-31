# vid-dl: playlists, download queue, and subtitle burn-in

**Date:** 2026-08-31
**Branch:** `feature/queue-playlists-subtitles`
**Upstream:** `jpasden/vid-dl` (read-only); work lives on a fork under `npaine01`

## Context

vid-dl today downloads one video at a time. `server.py` (250 lines) wraps `yt-dlp`
behind a local HTTP server, holds jobs in an in-memory dict, and hardcodes
`--no-playlist`. The UI drives a single download and polls for its progress.

This spec adds playlist handling, a serial download queue, and subtitle burn-in,
plus a repair pass for YouTube's auto-generated captions.

## Goals

1. Paste a playlist URL, pick which videos to download, queue them.
2. A serial queue that processes items one at a time and can be stopped.
3. Burn subtitles permanently into the picture, as HandBrake does.
4. Handle Chinese and Japanese subtitles correctly, plus Italian and Spanish.
5. Repair YouTube rolling-ASR caption files automatically.

## Non-goals

- Parallel downloads. Serial only.
- Queue persistence across restarts.
- Reordering or retrying queue items.
- General transcode controls (codec, CRF, resize). Burn-in defaults are chosen.
- Punctuation restoration or ASR word correction. See "Deliberate omissions".

## Guiding constraint

**Everything here is additive and optional.** Someone who wants an MP3 must
never encounter a subtitle option, an ffmpeg prompt, or a probe delay. The
plain download path stays as fast and dependency-light as it is today. No
install nagging at startup; the launcher continues to install only `yt-dlp`,
which is load-bearing.

## Generality constraint

**The program contains mechanisms, never content.** No domain vocabulary, no
corpus-specific rules, no bundled correction data ships with it. Every feature
must hold for an arbitrary video in an arbitrary language from an arbitrary
source. Specific files are used to *validate* behaviour during development;
they never become part of it.

Concretely, this rules out:

- Hardcoded proper nouns, names, or subject-matter word lists
- Assuming English, or any language, anywhere in the repair path
- Assuming YouTube as the source (the ASR detector gates on file *structure*,
  which any rolling-caption producer generates)
- Assuming captions are unpunctuated, or that ASR quality is uniform
- Committing third-party caption files to the repository as fixtures

`subs.py` additionally carries no macOS dependency and no external dependency,
so it is usable as a standalone cross-platform tool independent of the app.

## Architecture

Five Python modules. Still standard-library only, still double-click to run.

| Module | Responsibility |
|---|---|
| `server.py` | HTTP routing, static files, `main()`. No subprocess logic. |
| `ytdlp.py` | Playlist expansion, subtitle probing, download command building, progress parsing |
| `media.py` | ffmpeg capability detection, burn/mux commands, language to font mapping, ffmpeg progress |
| `subs.py` | SRT parsing, rolling-ASR detection, caption repair. Pure text, no I/O beyond read/write |
| `jobs.py` | `Job` model and the serial queue worker |
| `files.py` | Output-folder scanning, native Finder picker |

`jobs.py` is deliberately not named `queue.py`, which would shadow the stdlib
`queue` module the worker uses.

Frontend splits `index.html` into `index.html` / `app.js` / `style.css`.

## ffmpeg detection

Homebrew slimmed its core `ffmpeg` formula. Its dependencies are now
`dav1d, lame, libvmaf, libvpx, openssl@3, opus, sdl2-compat, svt-av1, x264,
x265, xz` -- no libass, no freetype, no fontconfig. A stock `brew install ffmpeg`
therefore **cannot burn subtitles**: the `subtitles`, `ass`, and `drawtext`
filters are all absent. The replacement is `ffmpeg-full`, which pulls in
`libass, fontconfig, freetype, harfbuzz, fribidi` -- but it is **keg-only**, so
it installs to `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` and never appears on
`PATH`. `shutil.which("ffmpeg")` will keep finding the incapable one.

At startup, probe these candidates in order, running `ffmpeg -hide_banner -filters`
on each and looking for a `subtitles` filter line:

1. `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`
2. `/usr/local/opt/ffmpeg-full/bin/ffmpeg`
3. `shutil.which("ffmpeg")`
4. `/opt/homebrew/bin/ffmpeg`, `/usr/local/bin/ffmpeg`

Produce two slots: `ffmpeg` (any working binary -- merging, MP3, soft-subs) and
`ffmpeg_burn` (libass-capable, may be `None`). They may be different binaries.
`h264_videotoolbox` availability is detected the same way via `-encoders`.

When `ffmpeg_burn` is `None`, burn options are disabled client-side **and**
rejected server-side, with the message naming `brew install ffmpeg-full`. The
hint appears inline next to the disabled control, not as a startup banner.

## Caption repair (`subs.py`)

### The problem

YouTube auto-captions imitate broadcast rolling captions. Downloaded as SRT,
the scroll is baked in as duplicated text. Each line of speech is written
three times: once as the lower line of a two-line cue, once alone in a 10 ms
"bridge" cue, and once as the upper line of the next cue. The effect is that a
subtitle you have already heard sits on screen over the audio of the next one.

Measured across five real files:

| File | Cues | Bridge cues (<=50ms) | Total lines | Unique lines |
|---|---|---|---|---|
| Ep 1 Trailer | 29 | 14 | 42 | 15 |
| Ep 2 Discovery | 137 | 68 | 204 | 69 |
| Ep 3 Wangal | 111 | 55 | 165 | 56 |
| Ep 4 Strangers | 139 | 69 | 207 | 70 |
| (unrelated video) | 959 | 479 | 1422 | 480 |

The pattern is universal to YouTube ASR, not specific to any one channel.

### Detection gate

```
BRIDGE_MS = 50

is_rolling(cues):
    if len(cues) < 8: return False
    bridge_ratio = count(cue.end - cue.start <= BRIDGE_MS) / len(cues)
    all_lines    = every line of every cue
    dup_ratio    = 1 - len(set(all_lines)) / len(all_lines)
    return bridge_ratio > 0.2 and dup_ratio > 0.25
```

Human-authored captions score far below both thresholds and are passed through
byte-identical. Only files that pass this gate are modified.

### Repair

```
MIN_CUE_MS = 400

clean_rolling(cues):
    seq, prev = [], None
    for i, cue in enumerate(cues):
        if not cue.lines: continue
        newest = cue.lines[-1]              # rule 1: last line is the new speech
        if newest == prev: continue         # rule 2: skip scroll frames
        # leading-edge fix: a line first appearing in a bridge cue inherits
        # the preceding cue's start, not the bridge's 10ms window
        start = cues[i-1].start if (cue.end - cue.start) <= BRIDGE_MS and i > 0 else cue.start
        seq.append((newest, start)); prev = newest

    out = []
    for i, (line, start) in enumerate(seq):
        end = seq[i+1][1] - 1 if i+1 < len(seq) else cues[-1].end     # rule 3: tile
        out.append(Cue(start, max(end, start + MIN_CUE_MS), line))
    return out
```

**The leading-edge fix is load-bearing and was found by testing.** Normally a
line is emitted from the long cue where it is the bottom line, and its bridge
arrives afterwards and is correctly skipped as a repeat. At the start of the
file -- and again after any speech pause where the caption display clears --
that order inverts: the line appears in its bridge *first*, is emitted with a
10 ms start, and rule 3 then gives it a 10 ms window that the `MIN_CUE_MS`
guard silently discards.

Without the fix, one line is lost per restart point: 1 line on each Bennelong
episode, 6 on the longer unrelated file. The lost lines are the openings of
each stretch of speech -- the worst ones to lose in a listening text.

### Post-conditions (asserted in tests)

- **No unique input line missing from the output.** This is the primary
  invariant. A line whose tiled window falls under `MIN_CUE_MS` is *extended*
  to that floor rather than discarded, and the job log records it. Nothing is
  ever dropped silently -- the original script's `>= 400` filter is what hid
  the leading-edge bug in the first place.
- No overlapping cues
- No cue shorter than `MIN_CUE_MS`
- Output cue count between 40% and 60% of input
- Mean cue duration between 1.5 s and 5.0 s (real files measure 2.46--2.78 s)

### Application

Repair runs automatically on every downloaded `.srt` that passes the gate.
The untouched original is kept alongside as `<name>.<lang>.raw.srt`. The
repaired file is what gets burned, muxed, or left as the sidecar.

Also exposed as a standalone action so existing files on disk can be repaired
without re-downloading.

### Related bug fix

`--sub-langs en.*` in the current `server.py` matches both `en` and `en-orig`,
writing two byte-identical files per download (verified by hash). Replaced with
the exact language code chosen from the probe.

## Playlist expansion and subtitle probing

`yt-dlp --flat-playlist --dump-single-json <url>` returns id, title and duration
for every entry in one fast call (verified against a real playlist). The UI
renders that as a checkbox list immediately.

Subtitle probing is a separate network round-trip **per video**, so it runs only
after you tick items, only on the ticked ones, four at a time. Results are
merged into a language list: tracks present in every selected video are listed
plainly, partial ones show "12 of 20 videos". Real captions and auto-generated
tracks are visually distinguished. Probing is skipped entirely when no subtitle
option is selected.

## The queue (`jobs.py`)

One worker thread, FIFO, in-memory. A job is a two-phase pipeline: **download**
then optionally **encode**, carrying a `stage` label so the UI reads
"Downloading 45%" then "Burning subtitles 12%". Encode progress comes from
`ffmpeg -progress pipe:1 -nostats`, divided by the duration reported by `ffprobe`.

A **Stop after current item** control drains the pending queue without killing
the running download.

A failed item does not stall the queue; it is marked errored and the worker
continues.

## Burning

```
ffmpeg -i in.mp4 \
  -vf "subtitles=subs.srt:force_style='FontName=<font>,FontSize=<size>'" \
  -c:v h264_videotoolbox -q:v 60 -c:a copy -movflags +faststart out.mp4
```

**Path escaping.** The `subtitles=` filter parses its argument as a filtergraph,
so a colon, comma, quote or bracket in the filename breaks it -- and YouTube
titles are full of those. Rather than escaping defensively, the job copies the
repaired `.srt` into a temp directory under a safe ASCII name and runs there.
This removes the entire class of bug.

**Encoder.** Hardware `h264_videotoolbox` when available (roughly 5--10x faster
than `libx264`, which matters across a queue), falling back to `libx264 -crf 18`.
No user-facing knobs, per scope. Audio is copied, never re-encoded.

**Soft-subs** use `-c copy -c:s mov_text` -- instant, no re-encode.

**Outputs.** Nothing is ever deleted: `Video.mp4` (clean), `Video [subbed].mp4`
(burned), `Video.<lang>.srt` (repaired), `Video.<lang>.raw.srt` (original).

### Language to font mapping

Font resolution goes through fontconfig. Verified working on this machine:

| Language | Font | Resolves to |
|---|---|---|
| `ja` | Hiragino Sans | `ヒラギノ角ゴシック W4.ttc` |
| `zh-Hans`, `zh-CN`, `zh` | PingFang SC | `PingFang.ttc` |
| `zh-Hant`, `zh-TW`, `zh-HK` | PingFang TC | `PingFang.ttc` |
| `ko` | Apple SD Gothic Neo | `AppleSDGothicNeo.ttc` |
| everything else | Helvetica Neue | `HelveticaNeue.ttc` |
| fallback | Arial Unicode MS | `Arial Unicode.ttf` |

Before burning, `fc-match` verifies the chosen font resolves to the family
requested. `fc-match` always returns *something* (LastResort), so the returned
family name must be compared, not just the exit code. A mismatch fails the job
immediately rather than after producing 40 minutes of tofu boxes.

Sizes Small/Medium/Large map to ASS `FontSize` values relative to libass's
default 384x288 script resolution. Initial values 18 / 24 / 30, **to be
confirmed against the preview during implementation** rather than assumed.

## Standalone burn tool

A collapsible section listing video files in `~/Downloads/YT` that have a
matching subtitle file beside them, plus a "Choose other files..." button that
opens a real Finder dialog via `osascript` for files anywhere on disk. Selecting
a pair enqueues a burn-only job.

## Preview burn

Renders roughly 8 seconds around the first subtitle cue, so font, size and
repair problems surface in about two seconds instead of after a full queue.

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| GET | `/`, `/app.js`, `/style.css` | Static files |
| GET | `/api/info` | Output dir, ffmpeg capabilities, `can_burn`, default quality |
| POST | `/api/resolve` | URL to `{kind: video\|playlist, title, items[]}` |
| POST | `/api/probe-subs` | Ticked URLs to available language tracks |
| POST | `/api/enqueue` | Add items to the queue |
| GET | `/api/queue` | All jobs, summary form |
| GET | `/api/status?id=` | One job, detail form (existing endpoint retained) |
| POST | `/api/stop` | Stop after current item |
| GET | `/api/library` | Burnable video/subtitle pairs in the output folder |
| POST | `/api/pick-file` | Native Finder picker |
| POST | `/api/preview` | 8-second preview burn |
| POST | `/api/repair-subs` | Repair an existing SRT in place |
| GET | `/api/open-folder` | Existing endpoint |

## Error handling

- No `yt-dlp`: existing message, unchanged.
- No burn-capable ffmpeg: option disabled client-side, rejected server-side.
- Font unavailable: job fails before encoding, naming the font and language.
- Video has no subtitles despite the probe: completes as a normal download with
  a logged warning. Does not fail.
- ffmpeg non-zero exit: job errors with the last 20 lines of stderr.
- Playlist URL that is really a single video: treated as a single video.
- One failed item never stalls the queue.

## Build order

Six shippable steps, each independently useful and testable:

1. **`subs.py` + CLI + tests.** SRT/VTT parsing, rolling detection, repair,
   glossary. Pure text, no dependencies, cross-platform, with a command-line
   entry point so it stands alone as a general tool independent of the app.
   Highest value, lowest risk, and settles the hardest correctness question
   first.
2. **Module split.** Move existing logic out of `server.py` into `ytdlp.py` /
   `media.py` / `jobs.py` with no behaviour change. Also fixes the
   `--sub-langs en.*` duplicate.
3. **Queue + stop.** Serial worker, multi-item UI, stop-after-current.
4. **Playlist expansion + probing.** Checkbox list, deferred per-item probe.
5. **Burning.** ffmpeg detection, font mapping, preview, soft-subs.
6. **Standalone burn tool.** Folder listing and Finder picker.

Steps 1--2 are safe on their own. The first user-visible change lands at 3.

## Testing

Standard-library `unittest`. No network, no encoding in tests.

- `test_subs.py` -- detection gate, repair, and glossary. Fixtures are
  **synthetic**: a generator builds rolling-caption SRTs reproducing the
  measured structure (bridge cues, three-fold line duplication, restart points
  after pauses) at arbitrary sizes and in arbitrary scripts, including Chinese
  and Japanese. Third-party caption files are not committed to the repository;
  real files are used as local validation during development only. Also covers
  a human-authored file passing through byte-identical, a VTT input, a file
  with no bridge cues, an empty file, and a single-cue file.
- `test_ytdlp.py` -- command building per mode/quality/subtitle combination;
  track parsing from captured `--dump-json` fixtures; playlist JSON to items.
- `test_media.py` -- capability parsing from captured `-filters` output of both
  a crippled and a full ffmpeg; font mapping; burn command construction
  including the temp-directory path handling; progress line parsing.
- `test_jobs.py` -- queue transitions with a fake runner: serial execution
  order, stop-after-current, and that an erroring item does not stall the queue.

## Deliberate omissions

**Punctuation restoration and ASR word correction are out of scope.** Repairing
the format does not repair the words. Measured on the sample files, Episodes 2--4
carry 0--2 punctuation marks across 56--70 lines, while Episode 1 is punctuated
and capitalised -- so the app cannot even assume captions are unpunctuated.

ASR fails hardest on exactly the material that matters: proper nouns and place
names. The sample files contain `will are a warrior been along` for
Woollarawarre Bennelong, `gagal`, `wam migle` and `baram` for clan names, and
`scientists dr. Peter Mitchell` for what is almost certainly
`scientist Dr Peter Mitchell`.

Correcting these requires checking against the source the video was scripted
from, not against what the words sound like. That is a judgement task, not a
heuristic one. A "capitalise after a long pause" rule would be wrong often
enough to be worse than nothing, and a confidently wrong proper noun in a
student handout is worse than a visible gap because nobody will check it.

The app repairs structure, which is deterministic and verifiable, and leaves
wording alone.

## Correction glossary

ASR fails hardest on vocabulary outside general speech -- proper nouns, place
names, technical and domain terms -- in any language. Repairing cue structure
does not touch this. The glossary is the general mechanism for it: an
**optional, user-supplied** list of literal substitutions applied after repair.

It ships empty. The program never contains corrections of its own.

**Format.** A plain UTF-8 text file, `wrong = right` per line, `#` for comments.
Chosen over JSON so it is editable by someone who does not write code. Located
by the user per download, or auto-detected as `glossary.txt` beside the output.

**Matching.** Literal, longest-first, so a short entry cannot clobber part of a
phrase a longer entry would have matched. Case-sensitive by default, since
capitalisation is often the very thing being corrected.

Word-boundary handling is script-aware rather than assumed: `\b` anchoring is
applied only where the term's edges are word characters in a script that
delimits words with spaces. Chinese, Japanese and Thai have no such boundaries,
so those terms match as plain substrings. Getting this wrong would make the
feature useless for exactly the languages this project has to support.

**Reporting.** Substitution is never silent. Each run reports every replacement
with its count, and -- more usefully -- flags **glossary entries that matched
nothing**, which means the ASR spelled the term differently than the author
assumed. That is a quality signal that is otherwise invisible.

**What it is not.** Not spell-checking, not fuzzy matching, not inference. It
applies exactly the substitutions it is given. Deciding what those should be
requires checking against the source a video was scripted from, which is a
judgement task and stays with the user.

## Deferred to measurement

Two defaults are guesses until there is output to look at, and the preview-burn
feature exists to settle them:

- **Encoder.** `h264_videotoolbox` vs `libx264 -crf 18` -- a real speed/quality
  trade whose right answer depends on encode times that have not been measured.
- **Font sizes.** 18 / 24 / 30 against libass's default 384x288 script
  resolution. Plausible, unverified.

Both are decided at step 5 with real numbers, not chosen on paper now.
