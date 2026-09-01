"""Tests for media.py -- locating a usable ffmpeg."""
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import media


def make_executable(folder, name="ffmpeg"):
    path = os.path.join(folder, name)
    with open(path, "w") as handle:
        handle.write("#!/bin/sh\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


class TestRejectsBrokenBinaries(unittest.TestCase):
    """A binary can exist, be marked executable, and still fail to run --
    installing ffmpeg-full upgrades shared libraries that an older ffmpeg
    formula still links against, leaving a dyld failure behind."""

    def test_skips_a_binary_that_cannot_execute(self):
        with tempfile.TemporaryDirectory() as folder:
            path = make_executable(folder)
            self.assertIsNone(media.find_ffmpeg(
                search_paths=[path], which=lambda n: None,
                verify=lambda p: False))

    def test_falls_through_to_a_working_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            broken = make_executable(folder, "ffmpeg")
            working = make_executable(folder, "ffmpeg2")
            self.assertEqual(
                media.find_ffmpeg(search_paths=[broken, working],
                                  which=lambda n: None,
                                  verify=lambda p: p == working),
                working)

    def test_rejects_a_broken_binary_found_on_the_path(self):
        self.assertIsNone(media.find_ffmpeg(
            search_paths=[], which=lambda n: "/usr/bin/ffmpeg",
            verify=lambda p: False))


class TestVerifyRuns(unittest.TestCase):
    def test_accepts_a_binary_that_reports_a_version(self):
        self.assertTrue(media.runs(sys.executable, args=("--version",),
                                   expect=""))

    def test_rejects_a_path_that_is_not_a_program(self):
        self.assertFalse(media.runs("/nonexistent/ffmpeg"))


class TestFindFfmpeg(unittest.TestCase):
    def test_finds_a_binary_at_a_known_location(self):
        with tempfile.TemporaryDirectory() as folder:
            path = make_executable(folder)
            self.assertEqual(
                media.find_ffmpeg(search_paths=[path], which=lambda n: None,
                                  verify=lambda p: True),
                path)

    def test_prefers_a_known_location_over_whatever_is_on_the_path(self):
        """Homebrew's ffmpeg-full is keg-only and never lands on PATH, but it
        is a superset of the slim formula, so it wins when both exist."""
        with tempfile.TemporaryDirectory() as folder:
            path = make_executable(folder)
            self.assertEqual(
                media.find_ffmpeg(search_paths=[path],
                                  which=lambda n: "/usr/bin/ffmpeg",
                                  verify=lambda p: True),
                path)

    def test_falls_back_to_the_path(self):
        with tempfile.TemporaryDirectory() as folder:
            on_path = make_executable(folder)
            self.assertEqual(
                media.find_ffmpeg(search_paths=["/nonexistent/ffmpeg"],
                                  which=lambda n: on_path,
                                  verify=lambda p: True),
                on_path)

    def test_returns_none_when_ffmpeg_is_not_installed(self):
        self.assertIsNone(
            media.find_ffmpeg(search_paths=["/nonexistent/ffmpeg"],
                              which=lambda n: None, verify=lambda p: True))

    def test_ignores_a_known_path_that_is_not_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "ffmpeg")
            open(path, "w").close()
            self.assertIsNone(
                media.find_ffmpeg(search_paths=[path], which=lambda n: None,
                                  verify=lambda p: True))


class TestBurnCapability(unittest.TestCase):
    """Burning needs libass, which Homebrew's core ffmpeg formula dropped.
    Presence of the binary says nothing about it."""

    # Captured verbatim from ffmpeg-full and the slim formula respectively.
    FULL = (" .. ass               V->V       Render ASS subtitles onto input video.\n"
            " .. subtitles         V->V       Render text subtitles onto input video.\n")
    SLIM = (" TS asubboost         A->A       Boost subwoofer frequencies.\n"
            " TS asubcut           A->A       Cut subwoofer frequencies.\n")

    def test_detects_a_build_with_the_subtitles_filter(self):
        self.assertTrue(media.can_burn("/x/ffmpeg", run=lambda p: self.FULL))

    def test_detects_a_build_without_it(self):
        self.assertFalse(media.can_burn("/x/ffmpeg", run=lambda p: self.SLIM))

    def test_treats_an_unrunnable_binary_as_incapable(self):
        def explode(path):
            raise OSError("boom")
        self.assertFalse(media.can_burn("/x/ffmpeg", run=explode))

    def test_is_not_fooled_by_the_word_appearing_in_a_description(self):
        listing = " .. showspectrum     V->V       Convert input to subtitles-like display.\n"
        self.assertFalse(media.can_burn("/x/ffmpeg", run=lambda p: listing))


class TestFontForLanguage(unittest.TestCase):
    def test_maps_japanese_to_a_font_with_kana_and_kanji(self):
        self.assertEqual(media.font_for("ja"), "Hiragino Sans")

    def test_maps_simplified_chinese_variants(self):
        for code in ("zh", "zh-Hans", "zh-CN", "zh-hans"):
            with self.subTest(code=code):
                self.assertEqual(media.font_for(code), "PingFang SC")

    def test_maps_traditional_chinese_variants(self):
        for code in ("zh-Hant", "zh-TW", "zh-HK"):
            with self.subTest(code=code):
                self.assertEqual(media.font_for(code), "PingFang TC")

    def test_maps_korean(self):
        self.assertEqual(media.font_for("ko"), "Apple SD Gothic Neo")

    def test_uses_a_latin_font_for_european_languages(self):
        for code in ("en", "it", "es", "en-GB", "pt-BR"):
            with self.subTest(code=code):
                self.assertEqual(media.font_for(code), "Helvetica Neue")

    def test_falls_back_for_an_unknown_language(self):
        self.assertEqual(media.font_for(None), "Helvetica Neue")

    def test_ignores_the_auto_generated_suffix(self):
        self.assertEqual(media.font_for("ja-orig"), "Hiragino Sans")


class TestFontVerification(unittest.TestCase):
    """fc-match always returns something -- LastResort if nothing matches --
    so the returned family has to be compared, not just the exit code."""

    def test_accepts_a_font_that_resolves_to_itself(self):
        self.assertTrue(media.font_available(
            "PingFang SC", match=lambda n: 'PingFang.ttc: "PingFang SC" "Regular"'))

    def test_rejects_a_fallback_substitution(self):
        self.assertFalse(media.font_available(
            "Nonexistent CJK", match=lambda n: 'LastResort.ttf: "LastResort" "Regular"'))

    def test_assumes_available_when_fontconfig_is_missing(self):
        """No fc-match is not evidence the font is absent; let ffmpeg decide."""
        def missing(name):
            raise OSError("no fc-match")
        self.assertTrue(media.font_available("Helvetica Neue", match=missing))


class TestSizes(unittest.TestCase):
    def test_offers_three_named_sizes(self):
        self.assertEqual(set(media.SIZES), {"small", "medium", "large"})

    def test_medium_is_the_default_for_an_unknown_name(self):
        self.assertEqual(media.font_size("enormous"), media.SIZES["medium"])


class TestBurnCommand(unittest.TestCase):
    def build(self, **kwargs):
        kwargs.setdefault("ffmpeg", "/x/ffmpeg")
        kwargs.setdefault("video", "/in/Clip: A Film.mp4")
        kwargs.setdefault("subtitle", "subs.srt")
        kwargs.setdefault("output", "/out/Clip [subbed].mp4")
        return media.burn_command(**kwargs)

    def video_filter(self, command):
        return command[command.index("-vf") + 1]

    def test_renders_the_subtitle_file_into_the_picture(self):
        self.assertIn("subtitles=subs.srt", self.video_filter(self.build()))

    def test_styles_the_text_with_the_chosen_font_and_size(self):
        vf = self.video_filter(self.build(font="PingFang SC", size=30))
        self.assertIn("FontName=PingFang SC", vf)
        self.assertIn("FontSize=30", vf)

    def test_never_puts_the_video_path_inside_the_filtergraph(self):
        """A colon or comma in a filename is filtergraph syntax. The subtitle
        is referenced by a bare safe name and the video passed as an input."""
        command = self.build()
        self.assertNotIn("Clip: A Film", self.video_filter(command))
        self.assertEqual(command[command.index("-i") + 1], "/in/Clip: A Film.mp4")

    def test_copies_the_audio_untouched(self):
        command = self.build()
        self.assertEqual(command[command.index("-c:a") + 1], "copy")

    def test_defaults_to_libx264_at_a_quality_target(self):
        command = self.build()
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")
        self.assertEqual(command[command.index("-crf") + 1], "18")

    def test_can_use_hardware_encoding_on_request(self):
        command = self.build(encoder="videotoolbox")
        self.assertEqual(command[command.index("-c:v") + 1], "h264_videotoolbox")
        self.assertNotIn("-crf", command)

    def test_reports_progress_in_a_parseable_form(self):
        self.assertIn("-progress", self.build())

    def test_writes_to_the_requested_output(self):
        self.assertEqual(self.build()[-1], "/out/Clip [subbed].mp4")

    def test_limits_the_preview_to_a_short_excerpt(self):
        command = self.build(preview_seconds=8, preview_start=12000)
        self.assertEqual(command[command.index("-t") + 1], "8")
        self.assertIn("-ss", command)


class TestMuxCommand(unittest.TestCase):
    def test_embeds_subtitles_without_re_encoding(self):
        command = media.mux_command(
            ffmpeg="/x/ffmpeg", video="/in/Clip.mp4", subtitle="/in/Clip.srt",
            output="/out/Clip.mp4", language="ja")
        self.assertEqual(command[command.index("-c:s") + 1], "mov_text")
        self.assertIn("-c", command)
        self.assertNotIn("-vf", command)

    def test_tags_the_track_with_its_language(self):
        command = media.mux_command(
            ffmpeg="/x/ffmpeg", video="/in/a.mp4", subtitle="/in/a.srt",
            output="/out/a.mp4", language="ja")
        self.assertTrue(any("language=jpn" in part for part in command))


class TestEncodeProgress(unittest.TestCase):
    def test_converts_elapsed_output_time_to_a_percentage(self):
        self.assertAlmostEqual(
            media.parse_encode_progress("out_time=00:00:30.000000", 60000)["percent"],
            50.0)

    def test_clamps_to_one_hundred(self):
        self.assertEqual(
            media.parse_encode_progress("out_time=00:01:10.000000", 60000)["percent"],
            100.0)

    def test_ignores_unrelated_lines(self):
        self.assertEqual(media.parse_encode_progress("frame=123", 60000), {})

    def test_ignores_progress_when_the_duration_is_unknown(self):
        self.assertEqual(
            media.parse_encode_progress("out_time=00:00:30.000000", None), {})
