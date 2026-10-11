"""Tests: the optional ffprobe report."""
from .support import *  # noqa: F403


class FindFfprobe(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_configured_file_wins(self):
        exe = self.tmp / "my-ffprobe.exe"
        exe.write_bytes(b"")
        with mock.patch.object(sb_quality.shutil, "which", return_value=r"C:\other\ffprobe.exe"):
            self.assertEqual(sb.find_ffprobe(exe), exe)

    def test_configured_but_missing_is_not_replaced_by_auto_detection(self):
        with mock.patch.object(sb_quality.shutil, "which", return_value=None):
            self.assertIsNone(sb.find_ffprobe(self.tmp / "gone.exe"))

    def test_auto_detection_order_is_path_then_fallback(self):
        fallback = self.tmp / "fallback-ffprobe.exe"
        fallback.write_bytes(b"")
        with mock.patch.object(sb_quality, "FFPROBE_FALLBACK", fallback):
            with mock.patch.object(sb_quality.shutil, "which", return_value=r"C:\on\path\ffprobe.exe"):
                self.assertEqual(sb.find_ffprobe(), Path(r"C:\on\path\ffprobe.exe"))
            with mock.patch.object(sb_quality.shutil, "which", return_value=None):
                self.assertEqual(sb.find_ffprobe(), fallback)
        with mock.patch.object(sb_quality, "FFPROBE_FALLBACK", self.tmp / "nope.exe"), \
                mock.patch.object(sb_quality.shutil, "which", return_value=None):
            self.assertIsNone(sb.find_ffprobe())

    # Regression guard. This constant was once written with the backslashes resolved as
    # escapes (form feed, backspace, form feed), so the documented fallback could never be
    # found and detection only worked where ffprobe happens to be on PATH.
    def test_fallback_path_is_the_documented_one(self):
        self.assertEqual(str(sb.FFPROBE_FALLBACK), r"C:\ffmpeg\bin\ffprobe.exe")


class ProbeFile(unittest.TestCase):
    def fake_run(self, stdout):
        return mock.Mock(return_value=mock.Mock(stdout=stdout))

    def test_command_and_parsing(self):
        run = self.fake_run("212.8,323456\n")
        with mock.patch.object(sb_quality.subprocess, "run", run):
            self.assertEqual(sb.probe_file(Path("ffprobe.exe"), Path("a.mp3")), (213, 323))
        cmd = run.call_args.args[0]
        self.assertEqual(cmd, ["ffprobe.exe", "-v", "error", "-show_entries", "format=duration,bit_rate",
                               "-of", "csv=p=0", "a.mp3"])
        self.assertEqual(run.call_args.kwargs["timeout"], 30)  # a corrupt file must not hang the run

    def test_unreadable_values_are_unknown_not_errors(self):
        for stdout, expected in (("", (None, None)), ("N/A,N/A\n", (None, None)), ("30.0\n", (30, None)),
                                 ("N/A,128000\n", (None, 128))):
            with mock.patch.object(sb_quality.subprocess, "run", self.fake_run(stdout)):
                self.assertEqual(sb.probe_file(Path("ffprobe.exe"), Path("a.mp3")), expected, stdout)

    def test_timeout_and_missing_executable_are_unknown_not_errors(self):
        with mock.patch.object(sb_quality.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffprobe", 30)):
            self.assertEqual(sb.probe_file(Path("ffprobe.exe"), Path("a.mp3")), (None, None))
        self.assertEqual(sb.probe_file(Path("no-such-ffprobe-xyz.exe"), Path("a.mp3")), (None, None))


class CheckDownloadsLogic(unittest.TestCase):
    """check_downloads with a scripted probe_file: the comparison, the log format, report-only."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        for name in ("a.mp3", "b.wav", "c.mp3", "d.mp3"):
            (self.tmp / name).write_bytes(b"audio")

    def check(self, playlist, rows, probes, tol=3):
        entries, _ = sb.convert_playlist(playlist)
        log: list[str] = []
        with mock.patch.object(sb_quality, "probe_file", side_effect=lambda exe, f: probes[f.name]):
            flagged = sb.check_downloads(entries, rows, [self.tmp] * len(rows), Path("ffprobe"), tol, log.append)
        return flagged, log

    def row(self, filepath, title, state="1"):
        return {"filepath": filepath, "artist": "", "title": title, "state": state}

    def test_mismatch_is_flagged_and_everything_stays_on_disk(self):
        playlist = ("A - One | 4:22\nB - Two | 4:37\nC - Three\nD - Four | 1:00\nE - Five | 1:00\nF - Six | 1:00\n")
        rows = [self.row("a.mp3", "A - One"), self.row("b.wav", "B - Two"), self.row("c.mp3", "C - Three"),
                self.row("d.mp3", "D - Four", state="2"),  # failed: never measured
                self.row("", "E - Five"),  # no file path: never measured
                self.row("f.mp3", "F - Six")]  # not on disk: never measured
        probes = {"a.mp3": (213, 323), "b.wav": (277, 2304), "c.mp3": (100, 128)}  # KeyError if anything else is probed
        flagged, log = self.check(playlist, rows, probes)
        self.assertEqual(flagged, ["a.mp3"])
        self.assertEqual(log[0], "CHECK  want=262 real=213 diff=-49 br=323kbps  MISMATCH  a.mp3")
        self.assertEqual(log[1], "CHECK  want=277 real=277 diff=+0  br=2304kbps  b.wav")
        self.assertIn("want=?", log[2])  # no length in the playlist line: numbers shown, never flagged
        self.assertIn("real=100", log[2])
        self.assertNotIn("MISMATCH", log[2])
        self.assertEqual(log[3], "CHECK 1 of 3 file(s) outside +-3 s: a.mp3")
        self.assertEqual(len(log), 4)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["a.mp3", "b.wav", "c.mp3", "d.mp3"])
        self.assertEqual((self.tmp / "a.mp3").read_bytes(), b"audio")  # not moved, renamed or changed

    def test_tolerance_edge_is_inclusive(self):
        rows = [self.row("a.mp3", "A - One"), self.row("b.wav", "B - Two")]
        flagged, _ = self.check("A - One | 1:40\nB - Two | 1:40\n", rows, {"a.mp3": (103, 128), "b.wav": (104, 128)})
        self.assertEqual(flagged, ["b.wav"])  # 3 s off is fine, 4 s off is not (tolerance 3)

    def test_negative_tolerance_prints_numbers_and_never_flags(self):
        rows = [self.row("a.mp3", "A - One")]
        flagged, log = self.check("A - One | 4:22\n", rows, {"a.mp3": (213, 323)}, tol=-1)
        self.assertEqual(flagged, [])
        self.assertEqual(log[0], "CHECK  want=262 real=213 diff=-49 br=323kbps  " + "a.mp3")
        self.assertEqual(log[1], "CHECK 0 of 1 file(s) flagged, length check is off (length tolerance -1)")

    def test_unreadable_file_is_unknown_not_flagged(self):
        flagged, log = self.check("A - One | 4:22\n", [self.row("a.mp3", "A - One")], {"a.mp3": (None, None)})
        self.assertEqual(flagged, [])
        self.assertIn("real=?", log[0])
        self.assertIn("br=?", log[0])

    def test_bitrate_is_reported_but_never_flags_a_file(self):
        flagged, log = self.check("A - One | 0:30\n", [self.row("a.mp3", "A - One")], {"a.mp3": (30, 83)})
        self.assertEqual(flagged, [])  # 83 kbps is far below the preferred 320, and still not a finding
        self.assertIn("br=83kbps", log[0])
        self.assertNotIn("MISMATCH", log[0])
        self.assertEqual(log[1], "CHECK 0 of 1 file(s) outside +-3 s")

    def test_nothing_measured_logs_nothing(self):
        flagged, log = self.check("A - One | 1:00\n", [self.row("a.mp3", "A - One", state="2")], {})
        self.assertEqual((flagged, log), ([], []))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg / ffprobe are not installed")
class FfprobeOnRealAudio(unittest.TestCase):
    """The ffprobe step against real mp3 files of a known length made with the local ffmpeg."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_probe_file_measures_a_known_duration_and_bitrate(self):
        duration, bitrate = sb.probe_file(FFPROBE, sample_mp3(30))
        self.assertAlmostEqual(duration, 30, delta=1)
        self.assertIsInstance(bitrate, int)
        self.assertGreater(bitrate, 0)

    def test_probe_file_gives_unknown_for_a_file_that_is_not_audio(self):
        junk = self.tmp / "junk.mp3"
        junk.write_text("this is not audio", encoding="utf-8")
        self.assertEqual(sb.probe_file(FFPROBE, junk), (None, None))

    def test_wrong_length_is_flagged_correct_length_is_not_and_files_stay(self):
        short = self.tmp / "Artist - Short Edit.mp3"
        right = self.tmp / "Artist - Right Length.mp3"
        for target in (short, right):
            shutil.copyfile(sample_mp3(30), target)
        before = short.read_bytes()
        entries, _ = sb.convert_playlist("Artist - Short Edit | 4:22\nArtist - Right Length | 0:30\n")
        rows = [{"filepath": short.name, "artist": "", "title": "Artist - Short Edit", "state": "1"},
                {"filepath": right.name, "artist": "", "title": "Artist - Right Length", "state": "1"}]
        log: list[str] = []
        flagged = sb.check_downloads(entries, rows, [self.tmp, self.tmp], FFPROBE, 3, log.append)
        self.assertEqual(flagged, [short.name])
        self.assertRegex(log[0], r"^CHECK  want=262 real=30 diff=-232 br=\d+kbps  MISMATCH  Artist - Short Edit\.mp3$")
        self.assertRegex(log[1], r"^CHECK  want=30 real=30 diff=\+0  br=\d+kbps  Artist - Right Length\.mp3$")
        self.assertEqual(log[2], f"CHECK 1 of 2 file(s) outside +-3 s: {short.name}")
        self.assertTrue(short.is_file() and right.is_file())  # the flagged file is left on disk
        self.assertEqual(short.read_bytes(), before)
        bitrate = int(re.search(r"br=(\d+)kbps", log[1]).group(1))
        self.assertLess(bitrate, 320)  # the sample is a low-bitrate file, and the right-length one was not flagged for it


class FfprobeStepGating(AppCase):
    """The ffprobe step runs after a real playlist run only: never in --dry-run, never with --preview."""

    def setUp(self):
        super().setUp()
        self.exe = self.tmp / "dummy.exe"
        self.exe.write_bytes(b"")
        self.playlist("A - One | 1:00\n")

    def test_off_unless_asked_for(self):
        with mock.patch.object(sb_runner, "run_process", return_value=sb.OK),                 mock.patch.object(sb_quality, "find_ffprobe") as find,                 mock.patch.object(sb_quality, "check_downloads") as check:
            self.assertEqual(self.batch(dry_run=False, sockseek=self.exe), 0)
        find.assert_not_called()
        check.assert_not_called()
        self.assertNotIn("ffprobe", self.log_text())

    def test_not_in_dry_run(self):
        with mock.patch.object(sb_quality, "find_ffprobe") as find, mock.patch.object(sb_quality, "check_downloads") as check:
            self.assertEqual(self.batch(dry_run=True, ffprobe_check=True), 0)
        find.assert_not_called()
        check.assert_not_called()
        self.assertNotIn("ffprobe", self.log_text())

    def test_not_with_preview(self):
        with mock.patch.object(sb_runner, "run_process", return_value=sb.OK), \
                mock.patch.object(sb_quality, "find_ffprobe") as find, mock.patch.object(sb_quality, "check_downloads") as check:
            self.assertEqual(self.batch(dry_run=False, sockseek=self.exe, ffprobe_check=True,
                                        opts=sb.Options(length_tol=-1, preview=True)), 0)
        find.assert_not_called()
        check.assert_not_called()
        self.assertIn("preview done", self.log_lines())


class FfprobeInRun(MockBase):
    """The ffprobe step inside a whole run against the real sockseek.exe in mock mode."""

    def mock_args(self):
        return super().mock_args() + SOCKSEEK_LENGTH_OFF  # sockseek's filter off, the script's own check stays on

    def real_batch(self, **kw):
        kw.setdefault("ffprobe_check", True)  # off by default since 2026-10-07, these tests want it
        return super().real_batch(**kw)

    def test_missing_ffprobe_warns_once_and_leaves_the_exit_code_alone(self):
        self.playlist(f"{LINE_A}\n{LINE_B}\n", name="one")
        self.playlist(f"{LINE_C}\n", name="two")
        self.assertEqual(self.real_batch(ffprobe=self.tmp / "no-such-ffprobe.exe"), 0)  # not an error
        lines = self.last_log_lines()
        self.assertEqual([l for l in lines if "ffprobe" in l], [MISSING_FFPROBE_WARN])  # one WARN, two playlists
        self.assertFalse([l for l in lines if l.startswith("CHECK")])
        self.assertEqual(lines[-1], "3 of 3 track(s) in the folders, 0 still missing (run #0001)")

    def test_missing_ffprobe_does_not_hide_or_add_a_failure(self):
        self.playlist(f"{LINE_A}\n{LINE_MISSING}\n")
        self.assertEqual(self.real_batch(ffprobe=self.tmp / "no-such-ffprobe.exe"), 0)  # the track is missing, not broken
        self.assertEqual(self.failed_lines(), [LINE_MISSING])

    def test_no_quality_option_reaches_the_sockseek_command_line(self):
        self.playlist(f"{LINE_A}\n")
        with mock.patch.object(sb_runner, "run_process", wraps=sb_runner.run_process) as spy:
            self.assertEqual(self.real_batch(ffprobe=self.tmp / "no-such-ffprobe.exe"), 0)
        cmd = spy.call_args.args[0]
        for gone in ("--min-bitrate", "--max-bitrate", "--strict-conditions",
                     "--pref-min-bitrate", "--pref-max-bitrate", "--pref-format"):
            self.assertNotIn(gone, cmd, gone)

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg / ffprobe are not installed")
    def test_wrong_length_download_is_flagged_in_the_log_and_stays_on_disk(self):
        shutil.copyfile(sample_mp3(30), self.mock_dir / "Alpha Band - First Song.mp3")  # real, 30 s long
        self.playlist("Alpha Band - First Song | 4:22\n")  # the playlist asks for 262 s
        self.assertEqual(self.real_batch(opts=sb.Options(length_tol=3), ffprobe=FFPROBE), 0)  # a report, not an error
        downloaded = self.output / "mix" / "Alpha Band - First Song.mp3"
        self.assertTrue(downloaded.is_file())  # left on disk
        lines = self.last_log_lines()
        check = [l for l in lines if l.startswith("CHECK")]
        self.assertEqual(len(check), 3, lines)
        # the sample is made with -q:a 9, so it is genuinely below the 256 kbps floor: both marks show
        self.assertRegex(check[0], r"^CHECK  want=262 real=30 diff=-232 br=\d+kbps  MISMATCH  LOWQ  "
                                   r"Alpha Band - First Song\.mp3$")
        self.assertRegex(check[1], r"^CHECK 1 file\(s\) below min-bitrate 256 .*Alpha Band - First Song\.mp3 \(\d+kbps\)$")
        self.assertEqual(check[2], "CHECK 1 of 1 file(s) outside +-3 s: Alpha Band - First Song.mp3")
        self.assertEqual(lines[-1],  # a mismatch changes neither the count nor the exit code
                         "1 of 1 track(s) in the folders, 0 still missing (run #0001)")

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg / ffprobe are not installed")
    def test_log_shows_failed_and_check_lines_together(self):
        shutil.copyfile(sample_mp3(30), self.mock_dir / "Alpha Band - First Song.mp3")
        self.playlist(f"Alpha Band - First Song | 0:30\n{LINE_MISSING}\n")
        self.assertEqual(self.real_batch(opts=sb.Options(length_tol=3), ffprobe=FFPROBE), 0)
        lines = self.last_log_lines()
        self.assertIn(f"FAILED  state=2 reason=9 {REASON9}  {LINE_MISSING}", lines)
        self.assertIn("run #0001: 1 arrived, 1 still missing, 1 of 2 in the folder", lines)
        self.assertTrue(any(re.fullmatch(
            r"CHECK  want=30 real=30 diff=\+0  br=\d+kbps  LOWQ  Alpha Band - First Song\.mp3", l)
            for l in lines), lines)
        self.assertIn("CHECK 0 of 1 file(s) outside +-3 s", lines)
        self.assertLess(lines.index("run #0001: 1 arrived, 1 still missing, 1 of 2 in the folder"),
                        lines.index("CHECK 0 of 1 file(s) outside +-3 s"))


if __name__ == "__main__":
    unittest.main()
