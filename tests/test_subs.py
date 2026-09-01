"""Tests for subs.py -- caption parsing, rolling-ASR repair, correction glossary."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import subs


class TestParseSrt(unittest.TestCase):
    def test_parses_a_single_cue_into_start_end_and_lines(self):
        text = "1\n00:00:01,500 --> 00:00:04,250\nHello there\n"
        cues = subs.parse(text)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].start, 1500)
        self.assertEqual(cues[0].end, 4250)
        self.assertEqual(cues[0].lines, ["Hello there"])


class TestParseVtt(unittest.TestCase):
    def test_parses_vtt_with_header_and_dot_separated_milliseconds(self):
        text = "WEBVTT\nKind: captions\n\n00:00:02.000 --> 00:00:05.000\nyes\n"
        cues = subs.parse(text)
        self.assertEqual(len(cues), 1)
        self.assertEqual((cues[0].start, cues[0].end), (2000, 5000))

    def test_strips_inline_word_timing_tags_from_vtt_text(self):
        text = ("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n"
                "hello<00:00:02.500><c> there</c>\n")
        cues = subs.parse(text)
        self.assertEqual(cues[0].lines, ["hello there"])

    def test_ignores_vtt_cue_settings_after_the_timestamp(self):
        text = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000 align:start position:0%\nhi\n"
        cues = subs.parse(text)
        self.assertEqual(cues[0].lines, ["hi"])


class TestSerialize(unittest.TestCase):
    def test_writes_cues_back_as_numbered_srt(self):
        cues = [subs.Cue(1500, 4250, ["Hello there"]),
                subs.Cue(4250, 6000, ["Second line"])]
        self.assertEqual(
            subs.to_srt(cues),
            "1\n00:00:01,500 --> 00:00:04,250\nHello there\n\n"
            "2\n00:00:04,250 --> 00:00:06,000\nSecond line\n",
        )

    def test_round_trips_through_parse_without_loss(self):
        original = [subs.Cue(0, 2000, ["one"]), subs.Cue(2000, 4000, ["two"])]
        reparsed = subs.parse(subs.to_srt(original))
        self.assertEqual([(c.start, c.end, c.lines) for c in reparsed],
                         [(c.start, c.end, c.lines) for c in original])


class TestParseBlankLineInsideCue(unittest.TestCase):
    """Rolling captions have two line slots; an empty top slot is a literal
    blank line inside the cue. Splitting blocks on blank lines alone tears
    such a cue in half and silently loses its text."""

    def test_keeps_text_that_follows_an_empty_top_slot(self):
        text = ("1\n00:00:01,760 --> 00:00:04,350\n\nfirst line\n\n"
                "2\n00:00:04,350 --> 00:00:04,360\nfirst line\n \n")
        cues = subs.parse(text)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].start, 1760)
        self.assertEqual(cues[0].lines, ["first line"])

    def test_treats_a_whitespace_only_bottom_slot_as_absent(self):
        text = "1\n00:00:00,000 --> 00:00:02,000\ntop line\n \n"
        self.assertEqual(subs.parse(text)[0].lines, ["top line"])


import fixtures

LATIN = ["the first thing spoken here", "and then the second thing",
         "followed by a third remark", "with a fourth to close it out",
         "and finally a fifth line", "plus a sixth for good measure",
         "a seventh arrives", "an eighth follows on",
         "the ninth is nearly last", "and the tenth ends it"]

JAPANESE = ["これは最初の行です", "次に二番目の行が来ます", "三番目の行はここにあります",
            "四番目の行も続きます", "五番目の行で終わります", "六番目の行を追加します",
            "七番目の行です", "八番目の行が続く", "九番目の行はほぼ最後", "十番目の行で完了"]

CHINESE = ["这是第一行文字", "然后是第二行", "第三行在这里", "第四行继续",
           "第五行结束了", "再加上第六行", "这是第七行", "第八行跟着来",
           "第九行快到最后", "第十行完成"]


class TestRollingDetection(unittest.TestCase):
    def test_detects_a_rolling_asr_file(self):
        self.assertTrue(subs.is_rolling(subs.parse(fixtures.rolling(LATIN))))

    def test_does_not_flag_a_human_authored_file(self):
        self.assertFalse(subs.is_rolling(subs.parse(fixtures.authored(LATIN))))

    def test_does_not_flag_a_file_too_short_to_judge(self):
        self.assertFalse(subs.is_rolling(subs.parse(fixtures.rolling(LATIN[:3]))))

    def test_detects_rolling_regardless_of_script(self):
        for name, lines in (("japanese", JAPANESE), ("chinese", CHINESE)):
            with self.subTest(script=name):
                self.assertTrue(subs.is_rolling(subs.parse(fixtures.rolling(lines))))

    def test_generator_reproduces_the_measured_cue_ratio(self):
        cues = subs.parse(fixtures.rolling(LATIN))
        self.assertEqual(len(cues), 2 * len(LATIN) - 1)


class TestRepair(unittest.TestCase):
    def test_recovers_every_line_once_in_order(self):
        repaired = subs.repair(subs.parse(fixtures.rolling(LATIN)))
        self.assertEqual([cue.lines for cue in repaired], [[l] for l in LATIN])

    def test_keeps_the_opening_line(self):
        """The line most at risk: it appears in the very first cue, whose top
        slot is blank."""
        repaired = subs.repair(subs.parse(fixtures.rolling(LATIN)))
        self.assertEqual(repaired[0].lines, [LATIN[0]])
        self.assertEqual(repaired[0].start, 1760)

    def test_leaves_authored_captions_untouched(self):
        original = subs.parse(fixtures.authored(LATIN))
        repaired = subs.repair(original)
        self.assertEqual([(c.start, c.end, c.lines) for c in repaired],
                         [(c.start, c.end, c.lines) for c in original])

    def test_recovers_every_line_in_any_script(self):
        for name, lines in (("japanese", JAPANESE), ("chinese", CHINESE)):
            with self.subTest(script=name):
                repaired = subs.repair(subs.parse(fixtures.rolling(lines)))
                self.assertEqual([c.lines for c in repaired], [[l] for l in lines])

    def test_produces_no_overlapping_cues(self):
        repaired = subs.repair(subs.parse(fixtures.rolling(LATIN)))
        for earlier, later in zip(repaired, repaired[1:]):
            self.assertLessEqual(earlier.end, later.start)

    def test_every_cue_ends_after_it_starts(self):
        for cue in subs.repair(subs.parse(fixtures.rolling(LATIN))):
            self.assertGreater(cue.end, cue.start)

    def test_halves_the_cue_count(self):
        cues = subs.parse(fixtures.rolling(LATIN))
        ratio = len(subs.repair(cues)) / len(cues)
        self.assertTrue(0.4 <= ratio <= 0.6, f"ratio was {ratio}")

    def test_handles_an_empty_file(self):
        self.assertEqual(subs.repair(subs.parse("")), [])

    def test_handles_a_single_cue(self):
        cues = subs.parse("1\n00:00:00,000 --> 00:00:02,000\nonly line\n")
        self.assertEqual([c.lines for c in subs.repair(cues)], [["only line"]])

    def test_reports_cues_left_shorter_than_the_readable_floor(self):
        cues = subs.parse(fixtures.rolling(LATIN, hold=200))
        repaired = subs.repair(cues)
        self.assertEqual(len(repaired), len(LATIN))          # nothing dropped
        self.assertTrue(subs.short_cues(repaired))            # but flagged


class TestGlossaryFormat(unittest.TestCase):
    def test_reads_entries_ignoring_comments_and_blank_lines(self):
        text = "# names\n\nbeen along = Bennelong\n\n  wangel  =  Wangal  \n"
        self.assertEqual(subs.parse_glossary(text),
                         [("been along", "Bennelong"), ("wangel", "Wangal")])

    def test_splits_on_the_first_equals_only(self):
        self.assertEqual(subs.parse_glossary("a = b = c"), [("a", "b = c")])


class TestGlossaryApplication(unittest.TestCase):
    def apply(self, glossary, lines):
        cues = [subs.Cue(0, 2000, [ln]) for ln in lines]
        out, report = subs.apply_glossary(cues, subs.parse_glossary(glossary))
        return [c.lines[0] for c in out], report

    def test_replaces_a_literal_phrase(self):
        text, _ = self.apply("been along = Bennelong", ["who was been along"])
        self.assertEqual(text, ["who was Bennelong"])

    def test_respects_word_boundaries_in_space_delimited_scripts(self):
        text, _ = self.apply("cat = dog", ["the cat in a category"])
        self.assertEqual(text, ["the dog in a category"])

    def test_matches_as_substring_in_scripts_without_word_boundaries(self):
        """CJK has no spaces, so boundary anchoring would never match."""
        text, _ = self.apply("猫 = 犬", ["猫が好きです"])
        self.assertEqual(text, ["犬が好きです"])

    def test_matches_japanese_phrases_mid_sentence(self):
        text, _ = self.apply("東京 = 京都", ["これは東京の話です"])
        self.assertEqual(text, ["これは京都の話です"])

    def test_applies_the_longest_entry_first(self):
        text, _ = self.apply("been along = Bennelong\nalong = alone",
                             ["it was been along today"])
        self.assertEqual(text, ["it was Bennelong today"])

    def test_is_case_sensitive(self):
        text, _ = self.apply("wangal = Wangal", ["Wangal and wangal"])
        self.assertEqual(text, ["Wangal and Wangal"])

    def test_counts_every_replacement(self):
        _, report = self.apply("a1 = A1", ["a1 here", "a1 and a1"])
        self.assertEqual(report, [("a1", "A1", 3)])

    def test_flags_entries_that_matched_nothing(self):
        _, report = self.apply("ghost = Ghost\nreal = Real", ["a real line"])
        self.assertEqual(subs.unmatched(report), ["ghost"])

    def test_leaves_text_alone_when_the_glossary_is_empty(self):
        text, report = self.apply("", ["untouched line"])
        self.assertEqual(text, ["untouched line"])
        self.assertEqual(report, [])


import subprocess
import tempfile
from pathlib import Path

SUBS_PY = Path(__file__).resolve().parent.parent / "subs.py"


class TestCommandLine(unittest.TestCase):
    def run_cli(self, *args, cwd):
        return subprocess.run([sys.executable, str(SUBS_PY), *args],
                              cwd=cwd, capture_output=True, text=True)

    def test_writes_a_repaired_file_alongside_the_original(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "clip.srt").write_text(fixtures.rolling(LATIN), encoding="utf-8")
            result = self.run_cli("clip.srt", cwd=folder)
            self.assertEqual(result.returncode, 0, result.stderr)
            repaired = Path(folder, "clip_CLEAN.srt")
            self.assertTrue(repaired.exists())
            self.assertEqual([c.lines[0] for c in subs.parse(repaired.read_text(encoding="utf-8"))],
                             LATIN)

    def test_processes_every_srt_in_the_folder_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("a.srt", "b.srt"):
                Path(folder, name).write_text(fixtures.rolling(LATIN), encoding="utf-8")
            self.run_cli(cwd=folder)
            self.assertTrue(Path(folder, "a_CLEAN.srt").exists())
            self.assertTrue(Path(folder, "b_CLEAN.srt").exists())

    def test_does_not_reprocess_its_own_output(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "clip.srt").write_text(fixtures.rolling(LATIN), encoding="utf-8")
            self.run_cli(cwd=folder)
            self.run_cli(cwd=folder)
            self.assertFalse(Path(folder, "clip_CLEAN_CLEAN.srt").exists())

    def test_leaves_authored_captions_alone_and_says_so(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "human.srt").write_text(fixtures.authored(LATIN), encoding="utf-8")
            result = self.run_cli("human.srt", cwd=folder)
            self.assertFalse(Path(folder, "human_CLEAN.srt").exists())
            self.assertIn("no change", result.stdout.lower())

    def test_applies_a_glossary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "clip.srt").write_text(
                fixtures.rolling(["been along was here"] + LATIN[1:]), encoding="utf-8")
            Path(folder, "gloss.txt").write_text("been along = Bennelong\n", encoding="utf-8")
            result = self.run_cli("clip.srt", "--glossary", "gloss.txt", cwd=folder)
            self.assertIn("Bennelong",
                          Path(folder, "clip_CLEAN.srt").read_text(encoding="utf-8"))
            self.assertIn("1", result.stdout)

    def test_warns_about_glossary_entries_that_matched_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "clip.srt").write_text(fixtures.rolling(LATIN), encoding="utf-8")
            Path(folder, "gloss.txt").write_text("nonexistent = Replaced\n", encoding="utf-8")
            result = self.run_cli("clip.srt", "--glossary", "gloss.txt", cwd=folder)
            self.assertIn("nonexistent", result.stdout)
            self.assertIn("matched nothing", result.stdout.lower())

    def test_reports_an_unreadable_path_without_crashing(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.run_cli("missing.srt", cwd=folder)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing.srt", result.stdout + result.stderr)


class TestRepairFile(unittest.TestCase):
    def test_writes_a_repaired_copy_and_reports_what_it_did(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, "in.srt")
            source.write_text(fixtures.rolling(LATIN), encoding="utf-8")
            target = Path(folder, "out.srt")
            stats = subs.repair_file(str(source), str(target))
            self.assertTrue(target.exists())
            self.assertTrue(stats["rolling"])
            self.assertEqual([c.lines[0] for c in subs.parse(target.read_text(encoding="utf-8"))],
                             LATIN)

    def test_copies_authored_captions_through_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, "in.srt")
            source.write_text(fixtures.authored(LATIN), encoding="utf-8")
            target = Path(folder, "out.srt")
            stats = subs.repair_file(str(source), str(target))
            self.assertFalse(stats["rolling"])
            self.assertEqual([c.lines for c in subs.parse(target.read_text(encoding="utf-8"))],
                             [[line] for line in LATIN])

    def test_applies_a_glossary_on_the_way_through(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, "in.srt")
            source.write_text(fixtures.rolling(["been along spoke"] + LATIN[1:]),
                              encoding="utf-8")
            target = Path(folder, "out.srt")
            stats = subs.repair_file(str(source), str(target),
                                     subs.parse_glossary("been along = Bennelong"))
            self.assertIn("Bennelong", target.read_text(encoding="utf-8"))
            self.assertEqual(stats["glossary"][0][2], 1)

    def test_converts_vtt_input_to_srt_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, "in.vtt")
            source.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nhello\n",
                              encoding="utf-8")
            target = Path(folder, "out.srt")
            subs.repair_file(str(source), str(target))
            self.assertIn("00:00:01,000 --> 00:00:04,000",
                          target.read_text(encoding="utf-8"))
