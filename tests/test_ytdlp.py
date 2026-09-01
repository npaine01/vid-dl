"""Tests for ytdlp.py -- command building and progress parsing."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ytdlp

OUT = "/tmp/out"
FFMPEG = "/opt/ffmpeg-full/bin/ffmpeg"


class TestDownloadCommand(unittest.TestCase):
    def build(self, **kwargs):
        kwargs.setdefault("url", "https://example.com/watch?v=x")
        kwargs.setdefault("output_dir", OUT)
        kwargs.setdefault("ffmpeg", FFMPEG)
        return ytdlp.build_download_command(**kwargs)

    def test_downloads_a_single_video_not_the_playlist_it_belongs_to(self):
        self.assertIn("--no-playlist", self.build())

    def test_writes_into_the_output_directory_with_a_title_template(self):
        command = self.build()
        self.assertEqual(command[command.index("-o") + 1],
                         os.path.join(OUT, "%(title)s.%(ext)s"))

    def test_caps_video_height_at_the_requested_quality(self):
        command = self.build(quality="720", ffmpeg=FFMPEG)
        self.assertIn("bestvideo[height<=720]+bestaudio/best[height<=720]",
                      command)

    def test_does_not_cap_height_when_asked_for_best(self):
        self.assertIn("bv*+ba/b", self.build(quality="best", ffmpeg=FFMPEG))

    def test_falls_back_to_premerged_formats_without_ffmpeg(self):
        self.assertIn("best[height<=1080]/b",
                      self.build(quality="1080", ffmpeg=None))

    def test_rejects_an_unknown_quality_and_uses_the_default(self):
        command = self.build(quality="9000", ffmpeg=FFMPEG)
        self.assertIn(f"bestvideo[height<={ytdlp.DEFAULT_QUALITY}]"
                      f"+bestaudio/best[height<={ytdlp.DEFAULT_QUALITY}]", command)

    def test_extracts_mp3_in_audio_mode(self):
        command = self.build(mode="audio")
        self.assertIn("-x", command)
        self.assertEqual(command[command.index("--audio-format") + 1], "mp3")

    def test_asks_for_no_subtitles_by_default(self):
        self.assertNotIn("--write-subs", self.build())

    def test_requests_exactly_the_chosen_subtitle_language(self):
        """`en.*` matches both `en` and `en-orig`, which makes yt-dlp write the
        same track twice under two names."""
        command = self.build(sub_lang="en")
        self.assertEqual(command[command.index("--sub-langs") + 1], "en")

    def test_accepts_auto_generated_captions_as_a_fallback(self):
        command = self.build(sub_lang="ja")
        self.assertIn("--write-subs", command)
        self.assertIn("--write-auto-subs", command)

    def test_converts_subtitles_to_srt_when_ffmpeg_is_present(self):
        command = self.build(sub_lang="en", ffmpeg=FFMPEG)
        self.assertEqual(command[command.index("--convert-subs") + 1], "srt")

    def test_leaves_subtitles_as_downloaded_without_ffmpeg(self):
        self.assertNotIn("--convert-subs", self.build(sub_lang="en", ffmpeg=None))

    def test_ignores_subtitles_in_audio_mode(self):
        self.assertNotIn("--write-subs", self.build(mode="audio", sub_lang="en"))


class TestFfmpegLocation(unittest.TestCase):
    """yt-dlp searches PATH for ffmpeg on its own. Homebrew's ffmpeg-full is
    keg-only and never on PATH, so the location has to be passed explicitly or
    every merge, MP3 extraction and subtitle conversion fails."""

    def test_tells_ytdlp_where_ffmpeg_is(self):
        command = ytdlp.build_download_command(
            url="u", output_dir=OUT, ffmpeg=FFMPEG)
        self.assertEqual(command[command.index("--ffmpeg-location") + 1], FFMPEG)

    def test_omits_the_location_when_there_is_no_ffmpeg(self):
        command = ytdlp.build_download_command(
            url="u", output_dir=OUT, ffmpeg=None)
        self.assertNotIn("--ffmpeg-location", command)


class TestProgressParsing(unittest.TestCase):
    def test_reads_the_percentage_from_a_download_line(self):
        line = "[download]  42.5% of ~ 118.20MiB at 3.30MiB/s ETA 00:21"
        self.assertEqual(ytdlp.parse_progress(line)["percent"], 42.5)

    def test_reads_the_total_size_from_a_download_line(self):
        line = "[download]  42.5% of ~ 118.20MiB at 3.30MiB/s ETA 00:21"
        self.assertEqual(ytdlp.parse_progress(line)["size"], "118.20MiB")

    def test_reads_the_destination_filename(self):
        line = "[download] Destination: /tmp/out/Some Video.f137.mp4"
        self.assertEqual(ytdlp.parse_progress(line)["filename"],
                         "Some Video.f137.mp4")

    def test_reads_the_filename_from_a_merge_line(self):
        line = '[Merger] Merging formats into "/tmp/out/Some Video.mp4"'
        self.assertEqual(ytdlp.parse_progress(line)["filename"], "Some Video.mp4")

    def test_returns_nothing_for_an_unrelated_line(self):
        self.assertEqual(ytdlp.parse_progress("[info] Downloading 1 format(s)"), {})
