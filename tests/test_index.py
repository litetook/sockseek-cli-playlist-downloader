"""Tests: sockseek's _index.csv: what is here, what failed, and how it reads."""
from .support import *  # noqa: F403


class IndexAndFailures(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_read_index_handles_commas_in_titles(self):
        path = self.tmp / "_index.csv"
        path.write_text(
            "filepath,artist,album,title,length,tracktype,state,failurereason\n"
            ',,,"Hello, World",200,0,2,9\n', encoding="utf-8")
        rows = sb.read_index([path])
        self.assertEqual(rows[0]["title"], "Hello, World")
        self.assertEqual(rows[0]["state"], "2")

    def test_failure_rows_only_non_ok_states_matched_by_title(self):
        entries, _ = sb.convert_playlist("A - One | 1:00\nB - Two | 2:00\n")
        rows = [
            {"title": "B - Two", "length": "120", "state": "2", "failurereason": "9"},
            {"title": "A - One", "length": "60", "state": "1", "failurereason": "0"},
        ]
        result = sb.failure_rows(entries, rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], {"playlist_line": "B - Two | 2:00", "index_title": "B - Two",
                                     "index_length": "120", "state": "2", "failurereason": "9"})

    def test_failure_rows_judges_states_directly(self):
        # 1 = downloaded, 3 = already present (skipped on a re-run): both are fine; 2 and unknown codes are not
        entries, _ = sb.convert_playlist("A - One | 1:00\nB - Two | 1:00\nC - Three | 1:00\nD - Four | 1:00\n")
        rows = [{"title": t, "length": "60", "state": s, "failurereason": "0"}
                for t, s in (("A - One", "1"), ("B - Two", "2"), ("C - Three", "3"), ("D - Four", "7"))]
        result = sb.failure_rows(entries, rows)
        self.assertEqual([(r["playlist_line"], r["state"]) for r in result],
                         [("B - Two | 1:00", "2"), ("D - Four | 1:00", "7")])

    def test_unmatched_failure_leaves_playlist_line_empty(self):
        entries, _ = sb.convert_playlist("A - One | 1:00\nB - Two | 2:00\nC - Three | 3:00\n")
        rows = [{"title": "something else", "length": "5", "state": "2", "failurereason": "9"}]
        result = sb.failure_rows(entries, rows)  # 1 row vs 3 entries: no positional guessing
        self.assertEqual(result[0]["playlist_line"], "")
        self.assertEqual(result[0]["index_title"], "something else")

    def test_read_index_with_dirs_pairs_each_row_with_its_index_folder(self):
        for sub in ("one", "two"):
            (self.tmp / sub).mkdir()
            (self.tmp / sub / "_index.csv").write_text(
                INDEX_HEADER + f"{sub}.mp3,,,T {sub},60,0,1,0\n", encoding="utf-8")
        rows, dirs = sb.read_index_with_dirs([self.tmp / "one" / "_index.csv", self.tmp / "two" / "_index.csv"])
        self.assertEqual([r["filepath"] for r in rows], ["one.mp3", "two.mp3"])
        self.assertEqual(dirs, [self.tmp / "one", self.tmp / "two"])

    def test_failed_csv_machinery_is_gone(self):
        # PLAN2 change 3: failures go into the run log, nothing writes a failed_*.csv any more
        self.assertFalse(hasattr(sb, "write_failed_csv"))
        self.assertFalse(hasattr(sb, "FAILED_COLUMNS"))


class FormatFailure(unittest.TestCase):
    def failure(self, **kw):
        base = {"playlist_line": "Funk Tribu - September - Cry For You (Funk Tribu Rework) | 5:37",
                "index_title": "Cry For You", "index_length": "337", "state": "2", "failurereason": "9"}
        base.update(kw)
        return base

    def test_matched_failure_shows_state_reason_and_the_playlist_line(self):
        self.assertEqual(
            sb.format_failure(self.failure()),
            "FAILED  state=2 reason=9 (no candidate passed the name/length/quality conditions)  "
            "Funk Tribu - September - Cry For You (Funk Tribu Rework) | 5:37")

    def test_reason_code_is_spelled_out_so_it_is_not_misread(self):
        # reason=9 does NOT mean "not on the network": run #0004 found two 320 kbps files for a
        # track the index reported as 9. Reading it literally is the mistake this line prevents.
        self.assertIn("conditions", sb.format_failure(self.failure(failurereason="9")))
        self.assertIn("did not come through", sb.format_failure(self.failure(failurereason="4")))
        self.assertIn("unknown reason code", sb.format_failure(self.failure(failurereason="7")))

    def test_unmatched_failure_says_so_instead_of_guessing(self):
        self.assertEqual(
            sb.format_failure(self.failure(playlist_line="", index_title="Some Title")),
            "FAILED  state=2 reason=9 (no candidate passed the name/length/quality conditions)  "
            "(no matching playlist line, index title: Some Title)")

    def test_missing_state_or_reason_is_shown_as_question_mark(self):
        line = sb.format_failure(self.failure(state="", failurereason=""))
        self.assertTrue(line.startswith("FAILED  state=? reason=? (unknown reason code)  "), line)


class PlaylistStatus(unittest.TestCase):
    """playlist_status: what counts as "already here". The rule is row AND file, nothing else."""

    LINES = "A - One | 1:00\nB - Two | 2:00\n"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name) / "mix"
        self.out.mkdir()

    def status(self, *rows, files=()):
        entries, _ = sb.convert_playlist(self.LINES)
        if rows:
            (self.out / "_index.csv").write_text(INDEX_HEADER + "".join(r + "\n" for r in rows),
                                                 encoding="utf-8")
        for name in files:
            (self.out / name).write_bytes(b"x" * 10)
        return entries, sb.playlist_status(entries, self.out)

    @staticmethod
    def lines(entries):
        return [e.original for e in entries]

    def test_no_index_at_all_means_everything_is_missing(self):
        _, status = self.status()
        self.assertEqual(self.lines(status.missing), ["A - One | 1:00", "B - Two | 2:00"])
        self.assertEqual(status.have, [])

    def test_a_row_with_its_file_on_disk_is_here(self):
        _, status = self.status("one.mp3,,,A - One,60,0,1,0", files=["one.mp3"])
        self.assertEqual(self.lines(status.have), ["A - One | 1:00"])
        self.assertEqual(self.lines(status.missing), ["B - Two | 2:00"])
        self.assertEqual(status.files["A - One | 1:00"].name, "one.mp3")

    def test_a_row_whose_file_was_deleted_is_missing_again(self):
        # the whole point of looking at the disk: the index alone would call this one done
        _, status = self.status("one.mp3,,,A - One,60,0,1,0")
        self.assertEqual(status.have, [])
        self.assertEqual(len(status.missing), 2)

    def test_state_3_counts_too_because_it_means_already_present(self):
        _, status = self.status("one.mp3,,,A - One,60,0,3,0", files=["one.mp3"])
        self.assertEqual(self.lines(status.have), ["A - One | 1:00"])

    def test_a_failed_row_is_missing_even_when_a_file_of_that_name_exists(self):
        _, status = self.status(",,,A - One,60,0,2,9", files=["one.mp3"])
        self.assertEqual(status.have, [])

    def test_a_row_whose_artist_was_split_off_still_finds_its_line(self):
        # --extract-artist writes the title in two columns; match_index puts them back together
        _, status = self.status("one.mp3,A,,One,60,0,1,0", files=["one.mp3"])
        self.assertEqual(self.lines(status.have), ["A - One | 1:00"])
