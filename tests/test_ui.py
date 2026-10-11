"""Tests: run.py: the menu, the status, the confirmation."""
from .support import *  # noqa: F403


class ParseChoice(unittest.TestCase):
    """run.parse_choice: 1-based for the person, 0-based in the result, no silent guessing."""

    def test_one_number(self):
        self.assertEqual(run.parse_choice("2", 3), [1])

    def test_several_numbers_keep_their_order_and_collapse_duplicates(self):
        self.assertEqual(run.parse_choice("3,1,3", 3), [2, 0])

    def test_spaces_work_like_commas(self):
        self.assertEqual(run.parse_choice("1 2", 2), [0, 1])

    def test_all_means_every_playlist(self):
        self.assertEqual(run.parse_choice("all", 3), [0, 1, 2])

    def test_empty_means_quit(self):
        self.assertEqual(run.parse_choice("  ", 3), [])

    def test_out_of_range_and_junk_are_not_understood(self):
        for text in ("0", "4", "x", "1,9", "-1"):
            self.assertIsNone(run.parse_choice(text, 3), text)


class RunUi(AppCase):
    """run.py end to end with scripted answers: menu, status, confirmation. No sockseek."""

    def setUp(self):
        super().setUp()
        self.output.mkdir(exist_ok=True)

    def have(self, name, *lines):
        """Pretend these playlist lines of <name> are already downloaded."""
        out = self.output / name
        out.mkdir(parents=True, exist_ok=True)
        rows = []
        for n, line in enumerate(lines, 1):
            entries, _ = sb.convert_playlist(line + "\n")
            file = f"{n:02d}.mp3"
            (out / file).write_bytes(b"x" * 10)
            rows.append(f"{file},,,{entries[0].track.title},{entries[0].track.length},0,1,0")
        (out / "_index.csv").write_text(INDEX_HEADER + "".join(r + "\n" for r in rows),
                                        encoding="utf-8")

    def ui(self, *answers, argv=(), source="1"):
        """run.main with scripted answers. Returns (exit code, everything printed, engine calls).

        `source` answers the opening "where from?" menu, which every interactive run starts
        with; these tests are about what happens after a .txt playlist was chosen, so it
        defaults to 1. The menu itself is tested in test_links.py.
        """
        said = ([] if source is None else [source]) + list(answers)
        calls, printed = [], []

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

    def test_menu_shows_how_much_of_each_playlist_is_already_here(self):
        self.playlist("A - One | 1:00\nB - Two | 2:00\n", name="mix")
        self.playlist("C - Three | 3:00\n", name="other")
        self.have("mix", "A - One | 1:00")
        code, text, calls = self.ui("")
        self.assertEqual((code, calls), (0, []))
        row = [l for l in text.splitlines() if " mix " in l]
        self.assertTrue(row, text)
        self.assertRegex(row[0], r"^\s*1\s+mix\s+2\s+1\s+1\s*$")
        self.assertTrue([l for l in text.splitlines() if " other " in l], text)

    def test_the_missing_tracks_are_shown_before_the_question(self):
        self.playlist("A - One | 1:00\nB - Two | 2:00\n")
        self.have("mix", "A - One | 1:00")
        code, text, calls = self.ui("1", "n")
        self.assertIn("mix: 2 tracks, 1 here, 1 missing", text)
        self.assertIn("Missing:", text)
        after = text.split("Missing:")[1]
        self.assertIn("B - Two | 2:00", after)
        self.assertNotIn("A - One | 1:00", after)  # what we already have is not listed
        self.assertLess(text.index("Missing:"), text.index("Download these 1?"))

    def test_no_means_nothing_is_downloaded(self):
        self.playlist("A - One | 1:00\n")
        code, text, calls = self.ui("1", "n")
        self.assertEqual((code, calls), (0, []))
        self.assertIn("Skipped.", text)

    def test_yes_runs_the_engine_for_that_playlist_only(self):
        self.playlist("A - One | 1:00\n", name="mix")
        self.playlist("C - Three | 3:00\n", name="other")
        code, text, calls = self.ui("1", "y")
        self.assertEqual((code, calls), (0, [["--only", "mix"]]))

    def test_all_takes_every_playlist(self):
        self.playlist("A - One | 1:00\n", name="mix")
        self.playlist("C - Three | 3:00\n", name="other")
        code, text, calls = self.ui("all", "y", "y")
        self.assertEqual(calls, [["--only", "mix"], ["--only", "other"]])

    def test_a_number_out_of_range_asks_again_instead_of_guessing(self):
        self.playlist("A - One | 1:00\n")
        code, text, calls = self.ui("5", "1", "n")
        self.assertIn("Type a number from 1 to 1", text)
        self.assertEqual(calls, [])

    def test_a_playlist_with_nothing_missing_asks_nothing(self):
        self.playlist("A - One | 1:00\n")
        self.have("mix", "A - One | 1:00")
        code, text, calls = self.ui("1")  # no answer prepared for a confirmation: there must be none
        self.assertEqual((code, calls), (0, []))
        self.assertIn("Nothing to do.", text)

    def test_only_skips_the_menu(self):
        self.playlist("A - One | 1:00\n", name="mix")
        code, text, calls = self.ui("y", argv=["--only", "mix"])
        self.assertEqual(calls, [["--only", "mix"]])
        self.assertNotIn("Playlists:", text)

    def test_an_unknown_only_name_is_an_error(self):
        self.playlist("A - One | 1:00\n", name="mix")
        code, text, calls = self.ui(argv=["--only", "nope"])
        self.assertEqual((code, calls), (2, []))
        self.assertIn("No playlist named", text)

    def test_yes_flag_downloads_without_asking(self):
        self.playlist("A - One | 1:00\n", name="mix")
        code, text, calls = self.ui(argv=["--only", "mix", "--yes"])  # no answers at all
        self.assertEqual(calls, [["--only", "mix"]])

    def test_other_flags_are_passed_through_to_the_engine(self):
        self.playlist("A - One | 1:00\n", name="mix")
        code, text, calls = self.ui(argv=["--only", "mix", "--yes", "--length-tol", "60", "--verbose"])
        self.assertEqual(calls, [["--only", "mix", "--length-tol", "60", "--verbose"]])

    def test_no_playlists_at_all_is_an_error(self):
        code, text, calls = self.ui()
        self.assertEqual((code, calls), (2, []))
        self.assertIn("No playlist .txt files", text)


class PathFlagsAreNotOnlyPassedOn(AppCase):
    """--output / --playlists / --config change what the MENU counts, not just the engine.

    Before: the menu read config.yaml, saw the track in the default output folder, said
    "Nothing to do" and exited 0 while the folder the user asked for stayed empty.
    """

    def ui(self, *answers, argv=(), source="1"):
        said = ([] if source is None else [source]) + list(answers)   # the opening menu
        calls, printed = [], []

        def ask(prompt):
            printed.append(prompt)
            if not said:
                raise EOFError
            return said.pop(0)

        with mock.patch.object(run, "APP_DIR", self.tmp):
            code = run.main(list(argv), ask=ask, out=printed.append,
                            engine=lambda args: calls.append(list(args)) or 0)
        return code, "\n".join(printed), calls

    def have_in(self, folder, line="A - One | 1:00", file="one.mp3"):
        folder.mkdir(parents=True, exist_ok=True)
        entries, _ = sb.convert_playlist(line + "\n")
        (folder / file).write_bytes(b"x")
        (folder / "_index.csv").write_text(
            INDEX_HEADER + f"{file},,,{entries[0].track.title},{entries[0].track.length},0,1,0\n",
            encoding="utf-8")

    def test_another_output_folder_is_the_one_that_is_measured(self):
        self.playlist("A - One | 1:00\n")
        self.have_in(self.output / "mix")          # present in the DEFAULT folder
        other = self.tmp / "elsewhere"
        code, text, calls = self.ui("y", argv=["--only", "mix", "--output", str(other)])
        self.assertIn("1 missing", text)           # the chosen folder has nothing
        self.assertEqual(calls, [["--only", "mix", "--output", str(other)]])
        self.assertEqual(code, 0)

    def test_a_folder_that_already_has_it_is_seen_as_done(self):
        self.playlist("A - One | 1:00\n")
        other = self.tmp / "elsewhere"
        self.have_in(other / "mix")
        code, text, calls = self.ui(argv=["--only", "mix", "--output", str(other)])
        self.assertIn("Nothing to do.", text)
        self.assertEqual(calls, [])

    def test_another_playlists_folder_is_listed(self):
        self.playlist("A - One | 1:00\n")          # in the default folder
        other = self.tmp / "other-lists"
        other.mkdir()
        (other / "second.txt").write_text("B - Two | 2:00\n", encoding="utf-8")
        code, text, calls = self.ui("", argv=["--playlists", str(other)])
        self.assertIn("second", text)
        self.assertNotIn("mix", text)

    def test_ctrl_c_in_the_engine_stops_the_session(self):
        self.playlist("A - One | 1:00\n", name="a")
        self.playlist("B - Two | 2:00\n", name="b")
        calls, printed = [], []
        with mock.patch.object(run, "APP_DIR", self.tmp):
            code = run.main(["all", "--yes"] if False else ["--yes"],
                            ask=lambda prompt: "all", out=printed.append,
                            engine=lambda args: calls.append(list(args)) or 130)
        self.assertEqual(calls, [["--only", "a"]])  # the second playlist is not started
        self.assertEqual(code, 130)
        self.assertIn("Interrupted.", "\n".join(printed))


class ChoiceIsNotFooledByOddDigits(unittest.TestCase):
    def test_a_superscript_digit_is_refused_not_crashed_on(self):
        # "2".isdigit() is true for these, and int() then raises
        for text in ("\u00b2", "\u00bd", "\u2075"):
            self.assertIsNone(run.parse_choice(text, 3), text)

    def test_plain_numbers_still_work(self):
        self.assertEqual(run.parse_choice("2", 3), [1])


class FirstRunAndTheOrderOfQuestions(AppCase):
    """What a new user sees, and when they are asked about a 50 MB download."""

    def ui(self, *answers, argv=(), bare=False, source="1"):
        said = ([] if source is None else [source]) + list(answers)   # the opening menu
        calls, printed = [], []

        def ask(prompt):
            printed.append(prompt)
            if not said:
                raise EOFError
            return said.pop(0)

        if bare:  # the fixture creates a login and a binary; a fresh clone has neither
            (self.tmp / sb.SOCKSEEK_LOCAL_CONF).unlink(missing_ok=True)
            for name in ("sockseek.exe", "sockseek"):
                (self.tmp / name).unlink(missing_ok=True)
        with mock.patch.object(run, "APP_DIR", self.tmp):
            code = run.main(list(argv), ask=ask, out=printed.append,
                            engine=lambda args: calls.append(list(args)) or 0)
        return code, "\n".join(printed), calls

    def test_a_first_run_asks_for_the_login_and_stops(self):
        self.playlist("A - One | 1:00\n")
        code, text, calls = self.ui(bare=True)
        self.assertEqual((code, calls), (2, []))
        self.assertIn("Put your Soulseek login in", text)
        self.assertIn("Then run this again", text)
        self.assertTrue((self.tmp / sb.SOCKSEEK_LOCAL_CONF).is_file())
        self.assertNotIn("Playlists:", text)  # no menu before the one thing that must be done

    def test_the_second_run_shows_the_menu(self):
        self.playlist("A - One | 1:00\n")
        self.ui(bare=True)  # creates the file
        (self.tmp / sb.SOCKSEEK_LOCAL_CONF).write_text("username = u\npassword = p\n",
                                                       encoding="utf-8")
        code, text, calls = self.ui("")
        self.assertIn("Playlists:", text)
        self.assertEqual(code, 0)

    def test_the_tool_is_asked_about_only_after_the_download_is_confirmed(self):
        self.playlist("A - One | 1:00\n")
        for name in ("sockseek.exe", "sockseek"):
            (self.tmp / name).unlink(missing_ok=True)
        code, text, calls = self.ui("1", "y", "n")
        self.assertEqual((code, calls), (2, []))
        self.assertLess(text.index("Missing:"), text.index("Download these 1?"))
        self.assertLess(text.index("Download these 1?"), text.index("sockseek 3.0.5 is missing"))
        self.assertIn("py setup.py", text)

    def test_saying_no_to_the_tracks_never_mentions_the_tool(self):
        self.playlist("A - One | 1:00\n")
        for name in ("sockseek.exe", "sockseek"):
            (self.tmp / name).unlink(missing_ok=True)
        code, text, calls = self.ui("1", "n")
        self.assertEqual((code, calls), (0, []))
        self.assertNotIn("is missing. Download it?", text)  # never asked about the 50 MB
        self.assertNotIn("py setup.py", text)
