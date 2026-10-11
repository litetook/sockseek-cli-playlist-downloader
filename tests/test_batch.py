"""Tests: a whole run: setup, the mock sockseek, failures, run numbers."""
from .support import *  # noqa: F403


class DryRunAndSetup(AppCase):
    """Behaviour that needs no downloader: nothing is executed."""

    def test_dry_run_writes_list_with_length_and_skips_generated(self):
        self.playlist("Linds - Cry For You | 4:09\n")
        (self.playlists / "tracks_old.txt").write_text('s:"junk"\n', encoding="utf-8")
        self.assertEqual(self.batch(), 0)
        content = (self.tmp / "work" / "mix.list.txt").read_text(encoding="utf-8")
        self.assertEqual(content.strip(), 's:"title=Linds - Cry For You, length=249"')
        self.assertFalse((self.tmp / "work" / "tracks_old.list.txt").exists())
        self.assertFalse(self.output.exists())
        self.assertIn("dry run: ", self.log_text())
        self.assertIn("--length-tol=-1", self.log_text())

    def test_duplicate_playlist_lines_collapse_and_are_logged(self):
        self.playlist(f"{LINE_A}\n{LINE_A}\n{LINE_B}\n")
        self.assertEqual(self.batch(), 0)
        lines = (self.tmp / "work" / "mix.list.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("1 duplicate line(s) dropped", self.log_text())
        self.assertIn("2 tracks", self.log_text())

    def test_missing_sockseek_is_error(self):
        self.playlist("A - B | 1:00\n")
        self.assertEqual(self.batch(dry_run=False, sockseek=self.tmp / "missing.exe"), 2)
        self.assertIn("sockseek not found", self.log_text())

    def test_creates_missing_playlists_dir(self):
        self.playlists.rmdir()
        self.assertEqual(self.batch(), 2)
        self.assertTrue(self.playlists.is_dir())

    def test_empty_playlists_dir_is_error(self):
        self.assertEqual(self.batch(), 2)
        self.assertIn("no playlist .txt files", self.log_text())

    def test_only_with_no_match_exits_2_and_names_the_playlist(self):
        self.playlist("A - One | 1:00\n", name="mix")
        code, _, _ = self.main("--playlists", str(self.playlists), "--output", str(self.output),
                               "--config", str(self.tmp / "c.ini"), "--only", "nosuch", "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn(f"no playlist named 'nosuch' in {self.playlists}", self.log_text())
        self.assertNotIn("no playlist .txt files", self.log_text())

    def test_only_selects_one_playlist(self):
        self.playlist("A - One | 1:00\n", name="mix")
        self.playlist("B - Two | 1:00\n", name="other")
        self.assertEqual(self.batch(only="other"), 0)
        self.assertTrue((self.tmp / "work" / "other.list.txt").exists())
        self.assertFalse((self.tmp / "work" / "mix.list.txt").exists())

    # --- errors that must not stop the batch
    def test_non_utf8_playlist_does_not_stop_batch(self):
        (self.playlists / "a_bad.txt").write_bytes("Привіт | 1:00".encode("cp1251"))
        self.playlist("B - good | 1:00\n", name="z_ok")
        self.assertEqual(self.batch(), 0)
        self.assertTrue((self.tmp / "work" / "z_ok.list.txt").exists())
        self.assertIn("Привіт", (self.tmp / "work" / "a_bad.list.txt").read_text(encoding="utf-8"))
        self.assertIn("not valid UTF-8, decoded as cp1251", self.log_text())

    def test_oserror_in_one_playlist_does_not_stop_others(self):
        self.playlist("A - one | 1:00\n", name="a_first")
        self.playlist("B - two | 1:00\n", name="b_second")
        real = sb_batch.Batch.one
        calls = []

        def flaky(batch, file, *args, **kwargs):
            calls.append(file.stem)
            if file.stem == "a_first":
                raise PermissionError("denied")
            return real(batch, file, *args, **kwargs)

        with mock.patch.object(sb_batch.Batch, "one", flaky):
            self.assertEqual(self.batch(), 1)
        self.assertEqual(calls, ["a_first", "b_second"])  # second still processed
        self.assertTrue((self.tmp / "work" / "b_second.list.txt").exists())

    def test_ctrl_c_returns_130(self):
        self.playlist("A - one | 1:00\n")
        with mock.patch.object(sb_batch.Batch, "one", side_effect=KeyboardInterrupt):
            self.assertEqual(self.batch(), 130)


class MockSockseek(MockBase):
    # --- PLAN 5.1 / 5.2: one process per playlist, flat output, index, failures in the log
    def test_two_tracks_land_flat_without_list_subfolders(self):
        self.playlist(f"{LINE_A}\n{LINE_B}\n")
        self.assertEqual(self.real_batch(), 0)
        out = self.output / "mix"
        self.assertEqual(self.audio_in(out), ["Alpha Band - First Song.mp3", "Beta Crew - Second Song.mp3"])
        self.assertEqual([p for p in out.rglob("*.list")], [])  # no NNN.list / <stem>.list folder
        self.assertEqual([p for p in out.iterdir() if p.is_dir()], [])
        self.assertTrue((out / "_index.csv").is_file())  # --index-path really lands here
        self.assertEqual(self.stray_failed_csv(), [])
        self.assertIn("run #0001: 2 arrived, 0 still missing, 2 of 2 in the folder", self.log_lines())

    def test_one_process_for_the_whole_playlist(self):
        self.playlist(f"{LINE_A}\n{LINE_B}\n{LINE_C}\n")
        with mock.patch.object(sb_runner, "run_process", wraps=sb_runner.run_process) as spy:
            self.assertEqual(self.real_batch(), 0)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(len(self.audio_in(self.output / "mix")), 3)

    def test_missing_track_is_listed_in_the_run_log_and_no_csv_is_written(self):
        self.playlist(f"{LINE_A}\n{LINE_MISSING}\n{LINE_B}\n")
        # exit 0: the tool worked, one track is simply not shared by anyone
        self.assertEqual(self.real_batch(), 0)
        self.assertEqual(len(self.audio_in(self.output / "mix")), 2)
        lines = self.last_log_lines()
        # exactly one FAILED line for the track, with the raw index codes, then the summary with the run number
        failed_line = (f"FAILED  state=2 reason=9 "
                       f"(no candidate passed the name/length/quality conditions)  {LINE_MISSING}")
        self.assertEqual([l for l in lines if l.startswith("FAILED  state=")], [failed_line])
        self.assertEqual(self.failed_lines(), [LINE_MISSING])
        self.assertIn("run #0001: 2 arrived, 1 still missing, 2 of 3 in the folder", lines)
        self.assertLess(lines.index(failed_line),
                        lines.index("run #0001: 2 arrived, 1 still missing, 2 of 3 in the folder"))
        self.assertEqual(lines[-1], "2 of 3 track(s) in the folders, 1 still missing (run #0001)")
        # PLAN2 change 3: no failed_*.csv anywhere, and the only csv is sockseek's own index
        self.assertEqual(self.stray_failed_csv(), [])
        self.assertEqual(sorted(p.name for p in self.tmp.rglob("*.csv")), ["_index.csv"])

    def test_a_rerun_searches_only_what_is_still_missing(self):
        self.playlist(f"{LINE_A}\n{LINE_MISSING}\n{LINE_B}\n")
        self.assertEqual(self.real_batch(), 0)
        with mock.patch.object(sb_runner, "run_process", wraps=sb_runner.run_process) as spy:
            self.assertEqual(self.real_batch(), 0)
        wanted = sb.convert_playlist(LINE_MISSING)[0][0].list_line
        sent = Path(spy.call_args.args[0][1]).read_text(encoding="utf-8").splitlines()
        self.assertEqual([l for l in sent if l.strip()], [wanted])  # only the one that is absent
        self.assertIn("3 tracks, 2 already here, 1 missing, length tolerance off",
                      self.last_log_lines())
        # no generated playlist is left behind any more
        self.assertEqual(sorted(p.name for p in self.playlists.iterdir()), ["mix.txt"])

    # --- re-running is the normal workflow: rows flip to state=3 ("already present") and are not failures
    def test_a_rerun_with_nothing_missing_does_not_start_sockseek_at_all(self):
        self.playlist(f"{LINE_A}\n{LINE_B}\n")
        self.assertEqual(self.real_batch(), 0)
        index = self.output / "mix" / "_index.csv"
        self.assertEqual({r["state"] for r in read_csv(index)}, {"1"})
        with mock.patch.object(sb_runner, "run_process", wraps=sb_runner.run_process) as spy:
            self.assertEqual(self.real_batch(), 0)  # second run over the same output folder
        spy.assert_not_called()  # not even to let sockseek skip them itself
        lines = self.last_log_lines()
        self.assertIn("2 tracks, 2 already here, 0 missing, length tolerance off", lines)
        self.assertTrue(any("nothing to search" in l for l in lines), lines)
        self.assertEqual(len(read_csv(index)), 2)  # the index is left exactly as it was
        self.assertEqual(len(self.audio_in(self.output / "mix")), 2)
        self.assertEqual(self.failed_lines(), [])
        self.assertEqual(lines[-1], "2 of 2 track(s) in the folders, 0 still missing (run #0002)")

    def test_rerun_reports_only_the_track_that_is_still_missing(self):
        self.playlist(f"{LINE_A}\n{LINE_MISSING}\n")
        self.assertEqual(self.real_batch(), 0)
        self.assertEqual(self.real_batch(), 0)
        self.assertEqual(self.failed_lines(), [LINE_MISSING])  # skipped track A is not listed


class FailuresInLog(AppCase):
    """PLAN2 change 3 with a scripted downloader that leaves a hand-made _index.csv behind."""

    def setUp(self):
        super().setUp()
        self.exe = self.tmp / "dummy.exe"
        self.exe.write_bytes(b"")  # only has to exist; it is never executed

    def index_writer(self, *rows):
        """A stand-in for run_process: writes <-o folder>/_index.csv, CREATES the files its rows
        name, and reports success. The files matter: a row that says "arrived" while nothing is
        on disk reads as missing, and that is the rule playlist_status enforces."""
        def fake(cmd, cwd, timeout_s, log):
            out = Path(cmd[cmd.index("-o") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "_index.csv").write_text(INDEX_HEADER + "".join(r + "\n" for r in rows), encoding="utf-8")
            for row in rows:
                name = row.split(",")[0].strip()
                if name:
                    (out / name).write_bytes(b"x" * 100)
            return sb.OK
        return fake

    def test_failed_rows_become_log_lines_in_the_documented_format(self):
        self.playlist("A - One | 1:00\nB - Two | 2:00\nC - Three | 3:00\n")
        fake = self.index_writer(
            "A - One.mp3,,,A - One,60,0,1,0", ",,,B - Two,120,0,2,9",
            "C - Three.mp3,,,C - Three,180,0,3,0")
        with mock.patch.object(sb_runner, "run_process", fake):
            self.assertEqual(self.batch(dry_run=False, sockseek=self.exe), 0)
        lines = self.last_log_lines()
        self.assertEqual([l for l in lines if l.startswith("FAILED")],
                         [f"FAILED  state=2 reason=9 {REASON9}  B - Two | 2:00"])
        self.assertIn("run #0001: 2 arrived, 1 still missing, 2 of 3 in the folder", lines)
        self.assertEqual(self.stray_failed_csv(), [])

    def test_a_stale_index_row_is_ignored_not_counted_as_a_track(self):
        # the index is cumulative: a track dropped from the playlist leaves its row behind for
        # ever. The report is driven by the PLAYLIST now, so such a row simply does not appear -
        # it used to read as "31 failed of 30 tracks".
        self.playlist("A - One | 1:00\nB - Two | 2:00\n")
        fake = self.index_writer("A - One.mp3,,,A - One,60,0,1,0", ",,,Dropped Long Ago,99,0,2,9")
        with mock.patch.object(sb_runner, "run_process", fake):
            self.assertEqual(self.batch(dry_run=False, sockseek=self.exe), 0)
        self.assertEqual(self.failed_lines(), ["B - Two | 2:00"])
        self.assertNotIn("Dropped Long Ago", " ".join(self.last_log_lines()))
        self.assertIn("run #0001: 1 arrived, 1 still missing, 1 of 2 in the folder",
                      self.last_log_lines())

    def test_a_row_that_claims_success_without_a_file_is_called_out(self):
        self.playlist("A - One | 1:00\n")

        def fake(cmd, cwd, timeout_s, log):  # the row names a file, nothing is written
            out = Path(cmd[cmd.index("-o") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "_index.csv").write_text(INDEX_HEADER + "A - One.mp3,,,A - One,60,0,1,0" + chr(10),
                                            encoding="utf-8")
            return sb.OK

        with mock.patch.object(sb_runner, "run_process", fake):
            self.assertEqual(self.batch(dry_run=False, sockseek=self.exe), 0)
        self.assertIn("WARN the index says this one arrived, but no file is on disk: A - One | 1:00",
                      self.last_log_lines())
        self.assertEqual(self.failed_lines(), ["A - One | 1:00"])

    def test_all_downloaded_means_no_failed_line_and_no_csv(self):
        self.playlist("A - One | 1:00\n")
        with mock.patch.object(sb_runner, "run_process", self.index_writer("A - One.mp3,,,A - One,60,0,1,0")):
            self.assertEqual(self.batch(dry_run=False, sockseek=self.exe), 0)
        self.assertEqual(self.failed_lines(), [])
        self.assertFalse([l for l in self.last_log_lines() if l.startswith("FAILED")])
        self.assertEqual(self.stray_failed_csv(), [])
        self.assertEqual(self.last_log_lines()[-1],
                         "1 of 1 track(s) in the folders, 0 still missing (run #0001)")


class RunNumber(unittest.TestCase):
    """next_run_number / run_label: logs/run_seq.txt holds the last number used."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.logs = Path(self._tmp.name) / "logs"
        self.logs.mkdir()
        self.seq = self.logs / "run_seq.txt"

    def test_fresh_folder_starts_at_one_and_says_the_counter_was_rebuilt(self):
        number, warnings = sb.next_run_number(self.logs)
        self.assertEqual(number, 1)
        self.assertEqual(self.seq.read_text(encoding="utf-8").strip(), "1")
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith("WARN "), warnings)
        self.assertIn("rebuilt", warnings[0])

    def test_counter_increments_and_is_written_back_at_once(self):
        self.seq.write_text("42\n", encoding="utf-8")
        self.assertEqual(sb.next_run_number(self.logs), (43, []))
        self.assertEqual(self.seq.read_text(encoding="utf-8").strip(), "43")
        self.assertEqual(sb.next_run_number(self.logs), (44, []))
        self.assertEqual(self.seq.read_text(encoding="utf-8").strip(), "44")

    def test_label_is_zero_padded_and_does_not_wrap(self):
        self.assertEqual((sb.run_label(0), sb.run_label(43), sb.run_label(9999)), ("0000", "0043", "9999"))
        self.assertEqual(sb.run_label(10000), "10000")
        self.seq.write_text("9999", encoding="utf-8")
        self.assertEqual(sb.next_run_number(self.logs)[0], 10000)

    def test_bad_counter_is_rebuilt_from_the_log_file_names_with_a_warning(self):
        for name in ("run_0007_2026-10-07_09-00-00.log", "run_0041_2026-10-07_10-00-00.log",
                     "run_abc_2026-10-07_10-00-00.log",  # not a number
                     "run_2026-10-06_21-57-27.log",  # the pre-PLAN2 name has no run number
                     "sockseek_0099_mix.log"):  # a sockseek log is not a run log
            (self.logs / name).write_text("x", encoding="utf-8")
        for bad in ("garbage", "", "  \n", "-3", "4.5", "12abc"):
            self.seq.write_text(bad, encoding="utf-8")
            number, warnings = sb.next_run_number(self.logs)
            self.assertEqual(number, 42, repr(bad))
            self.assertEqual(self.seq.read_text(encoding="utf-8").strip(), "42", repr(bad))
            self.assertEqual(len(warnings), 1, repr(bad))
            self.assertIn("rebuilt", warnings[0])
            self.assertIn("41", warnings[0])  # the highest number found

    def test_missing_counter_file_is_rebuilt_the_same_way(self):
        (self.logs / "run_0005_2026-10-07_09-00-00.log").write_text("x", encoding="utf-8")
        number, warnings = sb.next_run_number(self.logs)
        self.assertEqual(number, 6)
        self.assertEqual(len(warnings), 1)

    def test_unwritable_logs_folder_falls_back_to_zero_and_never_raises(self):
        gone = self.logs / "does" / "not" / "exist"  # the parent folder is missing: nothing can be written
        number, warnings = sb.next_run_number(gone)
        self.assertEqual(number, 0)
        self.assertTrue(any("cannot write" in w and "run number 0" in w for w in warnings), warnings)
        self.assertTrue(all(w.startswith("WARN ") for w in warnings), warnings)


class RunNumberInLog(AppCase):
    """The run number in the log file name, the first log line, the last log line and sockseek's log name."""

    LOG_NAME = re.compile(r"run_(\d{4})_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.log")

    def test_numbers_increment_across_two_runs_and_name_the_log_files(self):
        self.playlist("A - One | 1:00\n")
        self.assertEqual(self.batch(), 0)
        self.assertEqual(self.batch(), 0)
        seq = self.tmp / "logs" / "run_seq.txt"
        self.assertEqual(seq.read_text(encoding="utf-8").strip(), "2")
        logs = self.run_logs()
        self.assertEqual([self.LOG_NAME.fullmatch(p.name).group(1) for p in logs], ["0001", "0002"])
        for number, path in enumerate(logs, start=1):
            lines = self.strip_stamp(path.read_text(encoding="utf-8"))
            self.assertEqual(lines[0], f"run #{number:04d}")
            self.assertEqual(lines[-1], f"all done, nothing downloaded (run #{number:04d})")
        # a healthy counter is not "rebuilt": only the very first run of a fresh folder says so
        self.assertFalse([l for l in self.strip_stamp(logs[1].read_text(encoding="utf-8")) if "rebuilt" in l])

    def test_run_number_is_the_first_line_before_the_configuration_block(self):
        self.playlist("A - One | 1:00\n")
        code, _, _ = self.main("--playlists", str(self.playlists), "--output", str(self.output),
                               "--config", str(self.tmp / "c.ini"), "--dry-run", "--length-tol", "-1")
        self.assertEqual(code, 0)
        lines = self.log_lines()
        block = next(i for i, l in enumerate(lines) if l.startswith("effective configuration"))
        self.assertEqual(lines[0], "run #0001")
        self.assertGreater(block, 0)
        self.assertEqual([i for i, l in enumerate(lines) if l.startswith("run #")], [0])
        # the stdout copy of the log starts the same way
        self.assertTrue(self.out.splitlines()[0].endswith("] run #0001"), self.out)

    def test_corrupt_counter_is_rebuilt_from_existing_log_names(self):
        logs = self.tmp / "logs"
        logs.mkdir()
        for name in ("run_0009_2026-10-06_08-00-00.log", "run_0041_2026-10-06_09-00-00.log"):
            (logs / name).write_text("old\n", encoding="utf-8")
        (logs / "run_seq.txt").write_text("not a number", encoding="utf-8")
        self.playlist("A - One | 1:00\n")
        self.assertEqual(self.batch(), 0)
        self.assertEqual((logs / "run_seq.txt").read_text(encoding="utf-8").strip(), "42")
        newest = self.run_logs()[-1]
        self.assertTrue(newest.name.startswith("run_0042_"), newest.name)
        lines = self.last_log_lines()
        self.assertEqual(lines[0], "run #0042")
        warn = [l for l in lines if l.startswith("WARN") and "rebuilt" in l]
        self.assertEqual(len(warn), 1, lines)
        self.assertIn("41", warn[0])
        self.assertEqual(lines[-1], "all done, nothing downloaded (run #0042)")

    def test_missing_counter_is_rebuilt_from_existing_log_names(self):
        logs = self.tmp / "logs"
        logs.mkdir()
        (logs / "run_0100_2026-10-06_09-00-00.log").write_text("old\n", encoding="utf-8")
        self.playlist("A - One | 1:00\n")
        self.assertEqual(self.batch(), 0)
        self.assertEqual((logs / "run_seq.txt").read_text(encoding="utf-8").strip(), "101")
        self.assertTrue(any(l.startswith("WARN") and "rebuilt" in l for l in self.last_log_lines()))

    def test_broken_run_names_the_playlists_and_exits_one(self):
        self.playlist("A - One | 1:00\n", name="a")
        self.playlist("B - Two | 1:00\n", name="b")
        with mock.patch.object(sb_batch.Batch, "one", return_value=sb.Result(broke=True)):
            self.assertEqual(self.batch(), 1)
        self.assertEqual(self.last_log_lines()[-1], "ERROR this run broke on: a, b")

    def test_missing_tracks_alone_do_not_make_the_run_fail(self):
        self.playlist("A - One | 1:00\n", name="a")
        exe = self.tmp / "stub.exe"
        exe.write_bytes(b"")  # only has to exist: the playlist step is mocked out
        with mock.patch.object(sb_batch.Batch, "one",
                               return_value=sb.Result(total=3, missing=2)):
            self.assertEqual(self.batch(dry_run=False, sockseek=exe), 0)
        self.assertEqual(self.last_log_lines()[-1],
                         "1 of 3 track(s) in the folders, 2 still missing (run #0001)")

    def test_verbose_sockseek_log_is_named_after_the_run_number(self):
        self.playlist("A - One | 1:00\n")
        (self.tmp / "logs").mkdir()
        (self.tmp / "logs" / "run_seq.txt").write_text("6\n", encoding="utf-8")
        self.assertEqual(self.batch(verbose=True), 0)
        command = [l for l in self.last_log_lines() if l.startswith("dry run: ")][0]
        self.assertIn("--verbose", command)
        self.assertIn(str(self.tmp / "logs" / "sockseek_0007_mix.log"), command)
