"""Tests for ytdlp.py -- command building, parsing, and execution."""
import json
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


class TestFilenameReporting(unittest.TestCase):
    """yt-dlp announces several destinations per download: subtitle sidecars,
    per-format fragments, then the merged result. Only the last is the file
    the user actually asked for."""

    def test_ignores_subtitle_sidecar_destinations(self):
        line = "[download] Destination: /tmp/out/Clip.en.vtt"
        self.assertNotIn("filename", ytdlp.parse_progress(line))

    def test_ignores_srt_sidecars_too(self):
        line = "[download] Destination: /tmp/out/Clip.ja.srt"
        self.assertNotIn("filename", ytdlp.parse_progress(line))

    def test_reports_a_format_fragment_only_as_provisional(self):
        line = "[download] Destination: /tmp/out/Clip.f399.mp4"
        update = ytdlp.parse_progress(line)
        self.assertEqual(update["filename"], "Clip.f399.mp4")
        self.assertFalse(update["final"])

    def test_treats_the_merged_output_as_final(self):
        line = '[Merger] Merging formats into "/tmp/out/Clip.mp4"'
        update = ytdlp.parse_progress(line)
        self.assertEqual(update["filename"], "Clip.mp4")
        self.assertTrue(update["final"])

    def test_treats_extracted_audio_as_final(self):
        line = "[ExtractAudio] Destination: /tmp/out/Clip.mp3"
        update = ytdlp.parse_progress(line)
        self.assertEqual(update["filename"], "Clip.mp3")
        self.assertTrue(update["final"])


class TestAlreadyDownloaded(unittest.TestCase):
    def test_reports_the_name_of_a_file_already_on_disk(self):
        """yt-dlp prints no Destination line when the file already exists, so
        without this the job finishes with no filename at all."""
        line = "[download] /tmp/out/Clip.mp4 has already been downloaded"
        update = ytdlp.parse_progress(line)
        self.assertEqual(update["filename"], "Clip.mp4")
        self.assertTrue(update["final"])

    def test_ignores_an_already_downloaded_subtitle(self):
        line = "[download] /tmp/out/Clip.en.vtt has already been downloaded"
        self.assertNotIn("filename", ytdlp.parse_progress(line))


class TestPlaylistParsing(unittest.TestCase):
    PLAYLIST = {
        "_type": "playlist", "title": "Finding Bennelong", "id": "PL123",
        "entries": [
            {"_type": "url", "id": "aaa", "title": "Episode 1", "duration": 50,
             "url": "https://www.youtube.com/watch?v=aaa"},
            {"_type": "url", "id": "bbb", "title": "Episode 2", "duration": 615,
             "url": "https://www.youtube.com/watch?v=bbb"},
        ],
    }
    VIDEO = {"_type": "video", "id": "aaa", "title": "Episode 1", "duration": 50}

    def test_recognises_a_playlist(self):
        result = ytdlp.parse_resolution(self.PLAYLIST)
        self.assertEqual(result["kind"], "playlist")
        self.assertEqual(result["title"], "Finding Bennelong")
        self.assertEqual(len(result["items"]), 2)

    def test_carries_title_duration_and_url_for_each_item(self):
        first = ytdlp.parse_resolution(self.PLAYLIST)["items"][0]
        self.assertEqual(first["title"], "Episode 1")
        self.assertEqual(first["duration"], 50)
        self.assertEqual(first["url"], "https://www.youtube.com/watch?v=aaa")

    def test_recognises_a_single_video(self):
        result = ytdlp.parse_resolution(self.VIDEO)
        self.assertEqual(result["kind"], "video")
        self.assertEqual(len(result["items"]), 1)

    def test_builds_a_url_for_an_entry_that_only_has_an_id(self):
        payload = {"_type": "playlist", "title": "T",
                   "entries": [{"id": "zzz", "title": "Only id"}]}
        self.assertEqual(ytdlp.parse_resolution(payload)["items"][0]["url"],
                         "https://www.youtube.com/watch?v=zzz")

    def test_skips_unavailable_entries(self):
        payload = {"_type": "playlist", "title": "T",
                   "entries": [None, {"id": "ok", "title": "Fine"}]}
        self.assertEqual(len(ytdlp.parse_resolution(payload)["items"]), 1)


class TestSubtitleTracks(unittest.TestCase):
    """YouTube offers a handful of real tracks and ~157 machine translations of
    the automatic one. Presenting those as equals would be misleading."""

    INFO = {
        "language": "en",
        "subtitles": {"fr": [{"ext": "srt", "name": "French"}]},
        "automatic_captions": {
            "en": [{"ext": "srt", "name": "English"}],
            "en-orig": [{"ext": "srt", "name": "English (Original)"}],
            "ja": [{"ext": "srt", "name": "Japanese"}],
            "zh-Hans": [{"ext": "srt", "name": "Chinese (Simplified)"}],
            "aa": [{"ext": "srt", "name": "Afar"}],
        },
    }

    def tracks(self):
        return {t["code"]: t for t in ytdlp.parse_subtitle_tracks(self.INFO)}

    def test_marks_human_authored_captions_as_such(self):
        self.assertEqual(self.tracks()["fr"]["kind"], "captions")

    def test_marks_the_source_language_automatic_track_as_original(self):
        self.assertEqual(self.tracks()["en"]["kind"], "original")

    def test_marks_other_automatic_tracks_as_machine_translated(self):
        self.assertEqual(self.tracks()["ja"]["kind"], "translated")

    def test_collapses_the_duplicate_orig_variant(self):
        """`en` and `en-orig` are byte-identical for an English video."""
        self.assertNotIn("en-orig", self.tracks())

    def test_omits_translations_the_app_does_not_offer(self):
        self.assertNotIn("aa", self.tracks())

    def test_keeps_offered_translations(self):
        self.assertIn("zh-Hans", self.tracks())

    def test_orders_real_captions_before_machine_translations(self):
        kinds = [t["kind"] for t in ytdlp.parse_subtitle_tracks(self.INFO)]
        self.assertLess(kinds.index("captions"), kinds.index("translated"))

    def test_handles_a_video_with_no_subtitles_at_all(self):
        self.assertEqual(ytdlp.parse_subtitle_tracks({}), [])


class TestMergingTracksAcrossVideos(unittest.TestCase):
    def test_reports_how_many_videos_offer_each_language(self):
        merged = ytdlp.merge_tracks([
            [{"code": "en", "name": "English", "kind": "original"}],
            [{"code": "en", "name": "English", "kind": "original"},
             {"code": "ja", "name": "Japanese", "kind": "translated"}],
        ])
        by_code = {t["code"]: t for t in merged}
        self.assertEqual(by_code["en"]["count"], 2)
        self.assertEqual(by_code["ja"]["count"], 1)
        self.assertEqual(by_code["en"]["total"], 2)

    def test_lists_languages_every_video_has_first(self):
        merged = ytdlp.merge_tracks([
            [{"code": "ja", "name": "Japanese", "kind": "translated"}],
            [{"code": "ja", "name": "Japanese", "kind": "translated"},
             {"code": "en", "name": "English", "kind": "original"}],
        ])
        self.assertEqual(merged[0]["code"], "ja")

    def test_handles_no_videos(self):
        self.assertEqual(ytdlp.merge_tracks([]), [])


class TestResolvingAndProbing(unittest.TestCase):
    """Execution helpers. The runner is injected so no network is touched."""

    def test_resolves_a_url_into_items(self):
        payload = json.dumps({"_type": "playlist", "title": "T",
                              "entries": [{"id": "a", "title": "A"}]})
        result = ytdlp.resolve("u", run=lambda command: payload)
        self.assertEqual(result["kind"], "playlist")
        self.assertEqual(result["items"][0]["id"], "a")

    def test_raises_a_clear_error_when_yt_dlp_returns_nothing(self):
        with self.assertRaises(ytdlp.ResolveError):
            ytdlp.resolve("u", run=lambda command: "")

    def test_raises_a_clear_error_on_unparseable_output(self):
        with self.assertRaises(ytdlp.ResolveError):
            ytdlp.resolve("u", run=lambda command: "not json")

    def test_probes_several_videos_and_merges_their_languages(self):
        def run(command):
            url = command[-1]
            auto = {"en": [{"name": "English"}]}
            if url == "b":
                auto["ja"] = [{"name": "Japanese"}]
            return json.dumps({"language": "en", "automatic_captions": auto})

        merged = ytdlp.probe_many(["a", "b"], run=run)
        by_code = {t["code"]: t for t in merged}
        self.assertEqual(by_code["en"]["count"], 2)
        self.assertEqual(by_code["ja"]["count"], 1)

    def test_a_failing_probe_does_not_lose_the_others(self):
        def run(command):
            if command[-1] == "bad":
                raise OSError("nope")
            return json.dumps({"language": "en",
                               "automatic_captions": {"en": [{"name": "English"}]}})

        merged = ytdlp.probe_many(["good", "bad"], run=run)
        self.assertEqual(merged[0]["code"], "en")
        self.assertEqual(merged[0]["count"], 1)

    def test_probing_nothing_returns_nothing(self):
        self.assertEqual(ytdlp.probe_many([], run=lambda c: ""), [])
