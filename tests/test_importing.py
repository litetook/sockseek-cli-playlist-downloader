"""Tests: turning an exported list (m3u, csv/tsv, plain text) into a playlist file."""
from .support import *  # noqa: F403


class ImportM3u(unittest.TestCase):
    """#EXTINF carries the length in seconds, which is exactly what the search needs."""

    def read(self, text, name="list.m3u"):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            path.write_text(text, encoding="utf-8")
            return sb.Importer().read(path)

    def test_extinf_lines_become_playlist_lines(self):
        found = self.read("#EXTM3U\n"
                          "#EXTINF:249,Alpha Band - First Song\n"
                          "C:\\music\\first.mp3\n"
                          "#EXTINF:3875,Beta Crew - Long One\n"
                          "C:\\music\\long.flac\n")
        self.assertEqual(found.lines, ["Alpha Band - First Song | 4:09",
                                       "Beta Crew - Long One | 64:35"])
        self.assertEqual(found.source, "m3u")
        self.assertEqual(found.warnings, [])

    def test_unknown_length_leaves_the_line_without_one(self):
        # -1 is what players write when they do not know the duration
        found = self.read("#EXTM3U\n#EXTINF:-1,Alpha Band - First Song\npath.mp3\n")
        self.assertEqual(found.lines, ["Alpha Band - First Song"])

    def test_file_paths_and_other_tags_are_ignored(self):
        found = self.read("#EXTM3U\n#PLAYLIST:My Set\n#EXTINF:60,A - One\nA.mp3\nB.mp3\n")
        self.assertEqual(found.lines, ["A - One | 1:00"])

    def test_an_entry_without_a_title_is_named_in_a_warning(self):
        found = self.read("#EXTM3U\n#EXTINF:60,\nA.mp3\n#EXTINF:60,A - One\nB.mp3\n")
        self.assertEqual(found.lines, ["A - One | 1:00"])
        self.assertTrue(any("without a title" in w for w in found.warnings), found.warnings)

    def test_a_file_that_is_not_m3u_says_so(self):
        found = self.read("#EXTM3U\nnothing useful here\n")
        self.assertEqual(found.lines, [])
        self.assertTrue(any("no #EXTINF" in w for w in found.warnings), found.warnings)

    def test_the_format_is_recognised_by_content_too(self):
        found = self.read("#EXTM3U\n#EXTINF:60,A - One\nA.mp3\n", name="whatever.txt")
        self.assertEqual((found.source, found.lines), ("m3u", ["A - One | 1:00"]))


class ImportTable(unittest.TestCase):
    """csv/tsv exports: the columns are looked up by name, the rest is ignored."""

    def read(self, text, name="list.csv"):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            path.write_text(text, encoding="utf-8")
            return sb.Importer().read(path)

    def test_a_spotify_style_export(self):
        found = self.read('Track Name,Artist Name(s),Album Name,Duration (ms)\n'
                          'First Song,Alpha Band,Some Album,249000\n'
                          'Second Song,"Beta Crew, Gamma Duo",Other,200500\n')
        self.assertEqual(found.lines, ["Alpha Band - First Song | 4:09",
                                       "Beta Crew, Gamma Duo - Second Song | 3:21"])
        self.assertEqual(found.source, "table")

    def test_a_tab_separated_export_with_m_ss_times(self):
        found = self.read("Artist\tTitle\tTime\nAlpha Band\tFirst Song\t4:09\n", name="list.tsv")
        self.assertEqual(found.lines, ["Alpha Band - First Song | 4:09"])

    def test_seconds_are_taken_as_seconds(self):
        found = self.read("title,artist,duration\nFirst Song,Alpha Band,249\n")
        self.assertEqual(found.lines, ["Alpha Band - First Song | 4:09"])

    def test_milliseconds_without_a_hint_in_the_column_name(self):
        # 249000 cannot be seconds: that would be a 69-hour track
        found = self.read("title,artist,duration\nFirst Song,Alpha Band,249000\n")
        self.assertEqual(found.lines, ["Alpha Band - First Song | 4:09"])

    def test_a_long_dj_set_in_seconds_stays_in_seconds(self):
        found = self.read("title,artist,duration\nLong Set,Alpha Band,3875\n")
        self.assertEqual(found.lines, ["Alpha Band - Long Set | 64:35"])

    def test_a_missing_duration_column_is_a_warning_not_a_failure(self):
        found = self.read("Track Name,Artist\nFirst Song,Alpha Band\n")
        self.assertEqual(found.lines, ["Alpha Band - First Song"])
        self.assertTrue(any("no duration column" in w for w in found.warnings), found.warnings)

    def test_no_title_column_means_nothing_is_imported(self):
        found = self.read("bpm,key\n128,8A\n")
        self.assertEqual(found.lines, [])
        self.assertTrue(any("no title column" in w for w in found.warnings), found.warnings)

    def test_a_row_without_a_title_is_skipped_with_its_number(self):
        found = self.read("title,artist,duration\n,Alpha Band,100\nFirst Song,Alpha Band,249\n")
        self.assertEqual(found.lines, ["Alpha Band - First Song | 4:09"])
        self.assertTrue(any("row 2" in w for w in found.warnings), found.warnings)

    def test_a_track_without_an_artist_keeps_just_the_title(self):
        found = self.read("title,duration\nFirst Song,249\n")
        self.assertEqual(found.lines, ["First Song | 4:09"])


class ImportText(unittest.TestCase):
    """A plain list of names: the lines are kept as they are."""

    def read(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "list.txt"
            path.write_text(text, encoding="utf-8")
            return sb.Importer().read(path)

    def test_names_pass_through_and_comments_drop(self):
        found = self.read("Alpha Band - First Song\n# a note\n\n  Beta Crew - Second  Song \n")
        self.assertEqual(found.lines, ["Alpha Band - First Song", "Beta Crew - Second Song"])
        self.assertEqual(found.source, "text")

    def test_our_own_playlist_survives_a_round_trip(self):
        found = self.read("Alpha Band - First Song | 4:09\n")
        self.assertEqual(found.lines, ["Alpha Band - First Song | 4:09"])

    def test_an_empty_file_says_so(self):
        found = self.read("\n\n")
        self.assertEqual(found.lines, [])
        self.assertTrue(found.warnings)


class ImportFile(unittest.TestCase):
    """import_file writes the playlist, and never overwrites a hand-edited one by accident."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.playlists = self.dir / "Playlists"
        self.source = self.dir / "export.m3u"
        self.source.write_text("#EXTM3U\n#EXTINF:249,Alpha Band - First Song\nA.mp3\n",
                               encoding="utf-8")

    def test_the_playlist_is_written_and_named_after_the_file(self):
        written, found = sb.import_file(self.source, self.playlists)
        self.assertEqual(written, self.playlists / "export.txt")
        self.assertEqual(written.read_text(encoding="utf-8"), "Alpha Band - First Song | 4:09\n")
        self.assertEqual(found.lines, ["Alpha Band - First Song | 4:09"])

    def test_the_name_can_be_chosen(self):
        written, _ = sb.import_file(self.source, self.playlists, name="my-set")
        self.assertEqual(written.name, "my-set.txt")

    def test_an_existing_playlist_is_not_replaced_silently(self):
        self.playlists.mkdir()
        (self.playlists / "export.txt").write_text("hand written\n", encoding="utf-8")
        written, found = sb.import_file(self.source, self.playlists)
        self.assertIsNone(written)
        self.assertTrue(any("already exists" in w for w in found.warnings), found.warnings)
        self.assertEqual((self.playlists / "export.txt").read_text(encoding="utf-8"),
                         "hand written\n")
        written, _ = sb.import_file(self.source, self.playlists, overwrite=True)
        self.assertEqual(written.read_text(encoding="utf-8"), "Alpha Band - First Song | 4:09\n")

    def test_an_import_that_found_nothing_writes_nothing(self):
        empty = self.dir / "empty.m3u"
        empty.write_text("#EXTM3U\n", encoding="utf-8")
        written, found = sb.import_file(empty, self.playlists)
        self.assertIsNone(written)
        self.assertFalse(self.playlists.exists())

    def test_what_was_written_is_a_playlist_the_engine_can_read(self):
        written, _ = sb.import_file(self.source, self.playlists)
        playlist = sb.Playlist.from_file(written)
        self.assertEqual(playlist.warnings, [])
        self.assertEqual([e.track.length for e in playlist.entries], [249])
        self.assertEqual(playlist.entries[0].list_line,
                         's:"title=Alpha Band - First Song, length=249"')


class ImportThroughRunPy(AppCase):
    """run.py --import: the one command does the import too."""

    def ui(self, *answers, argv=()):
        said, calls, printed = list(answers), [], []

        def ask(prompt):
            printed.append(prompt)
            if not said:
                raise EOFError
            return said.pop(0)

        def engine(args):
            calls.append(list(args))
            return 0

        with mock.patch.object(run, "APP_DIR", self.tmp):
            code = run.main(list(argv), ask=ask, out=printed.append, engine=engine)
        return code, "\n".join(printed), calls

    def test_import_writes_the_playlist_and_tells_what_to_run_next(self):
        source = self.tmp / "export.m3u"
        source.write_text("#EXTM3U\n#EXTINF:249,Alpha Band - First Song\nA.mp3\n",
                          encoding="utf-8")
        code, text, calls = self.ui(argv=["--import", str(source)])
        self.assertEqual((code, calls), (0, []))  # importing never starts a download
        self.assertEqual((self.playlists / "export.txt").read_text(encoding="utf-8"),
                         "Alpha Band - First Song | 4:09\n")
        self.assertIn("1 track(s)", text)
        self.assertIn("py run.py --only export", text)

    def test_a_missing_file_is_an_error(self):
        code, text, calls = self.ui(argv=["--import", str(self.tmp / "nope.m3u")])
        self.assertEqual(code, 2)
        self.assertIn("No such file", text)

    def test_the_playlist_name_can_be_given(self):
        source = self.tmp / "export.csv"
        source.write_text("Track Name,Artist,Duration (ms)\nFirst Song,Alpha Band,249000\n",
                          encoding="utf-8")
        code, text, calls = self.ui(argv=["--import", str(source), "--as", "my-set"])
        self.assertEqual(code, 0)
        self.assertTrue((self.playlists / "my-set.txt").is_file())
