"""A playlist link -> playlist lines.

Nothing here touches the network: `fetch` and `run` are injected, so what is tested is our
parsing of shapes that were recorded from the real services on 2026-10-12 (Spotify's embed
page: props.pageProps.state.data.entity.trackList with title/subtitle/duration in ms;
yt-dlp's --print, one line per track).
"""
from .support import *

import json

from soulseek import links as sb_links

SPOTIFY_URL = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
SC_URL = "https://soundcloud.com/bonobo/sets/outlier-radio-on-nts"


def embed_page(tracks, name="Today's Top Hits"):
    """An embed page shaped like the real one: the JSON inside __NEXT_DATA__."""
    entity = {"name": name, "type": "playlist", "trackList": tracks}
    data = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return ('<!DOCTYPE html><html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(data) + "</script></body></html>")


def track(title, subtitle="", duration_ms=200000):
    return {"title": title, "subtitle": subtitle, "duration": duration_ms,
            "uri": "spotify:track:x"}


def ytdlp_out(rows):
    """yt-dlp --print output: playlist_title, title, uploader, duration per line."""
    return "".join(sb_links.FIELD_SEP.join(str(f) for f in row) + "\n" for row in rows)


class WhatCountsAsALink(unittest.TestCase):
    def test_the_shapes_the_services_actually_hand_out(self):
        for url, expected in (
                (SPOTIFY_URL, "spotify"),
                ("https://open.spotify.com/playlist/abc?si=9f2&pt=x", "spotify"),
                ("https://open.spotify.com/intl-de/playlist/abc", "spotify"),
                ("https://open.spotify.com/album/abc", "spotify"),
                ("spotify:playlist:abc", "spotify"),
                (SC_URL, "soundcloud"),
                ("https://m.soundcloud.com/u/sets/s", "soundcloud"),
                ("https://example.com/playlist", None),
                ("Playlists/mine.txt", None)):
            self.assertEqual(sb_links.detect(url), expected, url)

    def test_a_file_path_is_not_a_link_but_an_unknown_site_is(self):
        # "no such file" would be the wrong complaint about http://...
        self.assertFalse(sb.is_link("Playlists/mine.txt"))
        self.assertFalse(sb.is_link("C:/music/list.m3u"))
        self.assertTrue(sb.is_link("https://example.com/playlist"))

    def test_a_name_becomes_a_file_stem(self):
        self.assertEqual(sb.slug("Lo-Fi Beats (2024)"), "lo-fi-beats-2024")
        self.assertEqual(sb.slug("  my   list  "), "my-list")
        self.assertEqual(sb.slug("***"), "")


class SpotifyWithoutAnAccount(unittest.TestCase):
    """The embed page, which needs no developer application, no login and no Premium."""

    def read(self, page, url=SPOTIFY_URL):
        return sb.LinkReader(fetch=lambda _: page).read(url)

    def test_a_playlist_becomes_artist_title_and_a_length(self):
        linked = self.read(embed_page([track("Stop The Wedding!", "Ashe", 198840),
                                       track("the cure", "Olivia Rodrigo", 297090)]))
        self.assertEqual(linked.lines, ["Ashe - Stop The Wedding! | 3:19",
                                        "Olivia Rodrigo - the cure | 4:57"])
        self.assertEqual((linked.source, linked.name), ("spotify", "Today's Top Hits"))
        self.assertEqual(linked.warnings, [])

    def test_a_track_without_an_artist_keeps_just_the_title(self):
        linked = self.read(embed_page([track("Untitled", "", 60000)]))
        self.assertEqual(linked.lines, ["Untitled | 1:00"])

    def test_the_hundred_track_ceiling_is_reported_not_hidden(self):
        # measured 2026-10-12: two different long playlists both stopped at exactly 100,
        # so a longer playlist is silently cut unless we say so
        linked = self.read(embed_page([track(f"Song {i}", "A") for i in range(100)]))
        self.assertEqual(len(linked.lines), 100)
        self.assertTrue(any("100" in w and "cut" in w for w in linked.warnings),
                        linked.warnings)

    def test_a_shorter_playlist_is_not_accused_of_being_cut(self):
        linked = self.read(embed_page([track(f"Song {i}", "A") for i in range(99)]))
        self.assertEqual((len(linked.lines), linked.warnings), (99, []))

    def test_a_playlist_that_is_not_public_says_so(self):
        linked = self.read(embed_page([]))
        self.assertEqual(linked.lines, [])
        self.assertTrue(any("not public" in w for w in linked.warnings), linked.warnings)

    def test_a_changed_page_is_named_as_such_instead_of_crashing(self):
        linked = self.read("<html><body>nothing here</body></html>")
        self.assertEqual(linked.lines, [])
        self.assertTrue(any("__NEXT_DATA__" in w for w in linked.warnings), linked.warnings)

    def test_a_link_to_a_track_asks_for_a_playlist_link(self):
        linked = self.read(embed_page([track("x", "y")]),
                           url="https://open.spotify.com/track/abc")
        self.assertEqual(linked.lines, [])
        self.assertTrue(any("playlist or album link" in w for w in linked.warnings),
                        linked.warnings)

    def test_a_dead_network_is_a_warning_not_a_traceback(self):
        def boom(_):
            raise OSError("getaddrinfo failed")

        linked = sb.LinkReader(fetch=boom).read(SPOTIFY_URL)
        self.assertEqual(linked.lines, [])
        self.assertTrue(any("getaddrinfo" in w for w in linked.warnings), linked.warnings)


class SoundCloudThroughYtDlp(unittest.TestCase):
    """sockseek has no SoundCloud input type, so yt-dlp reads the set."""

    def read(self, rows, code=0, tool="yt-dlp.exe", cookies_from=None, calls=None):
        def run(args):
            if calls is not None:
                calls.append(args)
            return code, ytdlp_out(rows)

        tool_path = None if tool is None else Path(tool)
        return sb.LinkReader(run=run).read(SC_URL, tool_path, cookies_from)

    def test_a_set_becomes_lines_with_lengths(self):
        linked = self.read([("Outlier Radio", "OUTLIER Radio 003 on NTS", "bonobo", "7258.755")])
        self.assertEqual(linked.lines, ["bonobo - OUTLIER Radio 003 on NTS | 120:59"])
        self.assertEqual((linked.source, linked.name), ("soundcloud", "Outlier Radio"))

    def test_a_title_that_already_names_the_artist_is_left_alone(self):
        # SoundCloud uploaders are not artists: prefixing twice would break the search
        linked = self.read([("S", "Four Tet - Baby", "someuploader", "200")])
        self.assertEqual(linked.lines, ["Four Tet - Baby | 3:20"])

    def test_a_track_with_no_duration_keeps_the_name(self):
        linked = self.read([("S", "Some Mix", "dj", "NA")])
        self.assertEqual(linked.lines, ["dj - Some Mix"])

    def test_without_yt_dlp_it_says_what_to_run(self):
        linked = self.read([("S", "t", "u", "1")], tool=None)
        self.assertEqual(linked.lines, [])
        self.assertTrue(any("setup.py" in w for w in linked.warnings), linked.warnings)

    def test_an_empty_answer_points_at_the_browser_cookies(self):
        linked = self.read([])
        self.assertEqual(linked.lines, [])
        self.assertTrue(any("cookies-from-browser" in w for w in linked.warnings),
                        linked.warnings)

    def test_the_browser_login_is_passed_to_yt_dlp(self):
        calls = []
        self.read([("S", "t", "u", "1")], cookies_from="firefox", calls=calls)
        self.assertIn("--cookies-from-browser", calls[0])
        self.assertEqual(calls[0][calls[0].index("--cookies-from-browser") + 1], "firefox")

    def test_a_partly_failed_set_keeps_what_arrived_and_warns(self):
        linked = self.read([("S", "t", "u", "1")], code=1)
        self.assertEqual(len(linked.lines), 1)
        self.assertTrue(any("exited with 1" in w for w in linked.warnings), linked.warnings)


class ImportingALinkThroughRunPy(AppCase):
    """--import <link> writes a playlist file and stops there: downloading is a separate yes."""

    def ui(self, argv, reader, answers=()):
        said, printed, self.calls = list(answers), [], []

        def ask(prompt):
            printed.append(prompt)
            return said.pop(0) if said else ""

        def engine(args):
            self.calls.append(list(args))
            return 0

        with mock.patch.object(run, "APP_DIR", self.tmp):
            code = run.main(list(argv), ask=ask, out=printed.append, engine=engine,
                            reader=reader)
        return code, "\n".join(printed)

    def reader(self, page=None):
        return sb.LinkReader(fetch=lambda _: page or embed_page(
            [track("Stop The Wedding!", "Ashe", 198840)], name="Lo-Fi Beats"))

    def test_the_playlist_file_is_written_and_nothing_is_downloaded(self):
        code, text = self.ui(["--import", SPOTIFY_URL], self.reader())
        written = self.tmp / "Playlists" / "lo-fi-beats.txt"
        self.assertEqual(code, 0)
        self.assertEqual(written.read_text(encoding="utf-8"),
                         "Ashe - Stop The Wedding! | 3:19\n")
        self.assertIn("Now run: py run.py --only lo-fi-beats", text)

    def test_as_names_the_file(self):
        code, _ = self.ui(["--import", SPOTIFY_URL, "--as", "mine"], self.reader())
        self.assertEqual(code, 0)
        self.assertTrue((self.tmp / "Playlists" / "mine.txt").is_file())

    def test_an_existing_playlist_is_not_replaced_without_overwrite(self):
        self.playlist("Keep This | 1:00", name="mine")
        code, text = self.ui(["--import", SPOTIFY_URL, "--as", "mine"], self.reader())
        self.assertEqual(code, 2)
        self.assertIn("--overwrite", text)
        self.assertIn("Keep This", (self.tmp / "Playlists" / "mine.txt").read_text("utf-8"))

    def test_overwrite_replaces_it(self):
        self.playlist("Keep This | 1:00", name="mine")
        code, _ = self.ui(["--import", SPOTIFY_URL, "--as", "mine", "--overwrite"],
                          self.reader())
        self.assertEqual(code, 0)
        self.assertNotIn("Keep This",
                         (self.tmp / "Playlists" / "mine.txt").read_text("utf-8"))

    def test_a_link_we_cannot_read_is_not_mistaken_for_a_missing_file(self):
        code, text = self.ui(["--import", "https://example.com/list"], self.reader())
        self.assertEqual(code, 2)
        self.assertNotIn("No such file", text)
        self.assertIn("Spotify and SoundCloud", text)

    def test_a_soundcloud_link_offers_the_pinned_yt_dlp_instead_of_calling_it_unpinned(self):
        """The tool lookup must read dependencies.yaml, not config.yaml (which has no tools)."""
        for name in ("yt-dlp.exe", "yt-dlp"):
            (self.tmp / name).unlink(missing_ok=True)
        code, text = self.ui(["--import", SC_URL], self.reader(), answers=["n"])
        self.assertEqual(code, 2)
        self.assertNotIn("not pinned", text)
        self.assertIn("yt-dlp", text)
        self.assertIn("Download it?", text)
        self.assertIn("setup.py --all", text)


class TheOpeningMenu(ImportingALinkThroughRunPy):
    """Either drop a file in and download it, or paste a link and have it all happen."""

    def test_a_bare_run_offers_the_three_ways_in(self):
        self.playlist("A - One | 1:00\n")
        code, text = self.ui([], self.reader())
        self.assertEqual(code, 0)
        for expected in ("Where from?", "1  download a playlist from a .txt file",
                         "2  save a .txt from a Spotify link", "3  save a .txt from a SoundCloud"):
            self.assertIn(expected, text)

    def test_enter_at_the_menu_quits_without_doing_anything(self):
        self.playlist("A - One | 1:00\n")
        code, text = self.ui([], self.reader(), answers=[""])
        self.assertEqual((code, self.calls), (0, []))
        self.assertNotIn("Playlists:", text)

    def test_option_one_leads_to_the_playlist_chooser(self):
        self.playlist("A - One | 1:00\n", name="mix")
        code, text = self.ui([], self.reader(), answers=["1", ""])
        self.assertEqual(code, 0)
        self.assertIn("Playlists:", text)
        self.assertIn("mix", text)

    def test_a_wrong_answer_asks_again_instead_of_guessing(self):
        self.playlist("A - One | 1:00\n")
        code, text = self.ui([], self.reader(), answers=["7", "x", ""])
        self.assertEqual(code, 0)
        self.assertIn("Type 1, 2 or 3", text)

    def test_a_spotify_link_is_saved_and_then_downloaded(self):
        # the whole point: paste a link, and the download happens in the same run
        code, text = self.ui([], self.reader(), answers=["2", SPOTIFY_URL, "y"])
        self.assertEqual(code, 0)
        self.assertTrue((self.tmp / "Playlists" / "lo-fi-beats.txt").is_file())
        self.assertIn("Missing:", text)
        self.assertIn("Ashe - Stop The Wedding!", text)
        self.assertEqual(self.calls, [["--only", "lo-fi-beats"]])

    def test_the_download_still_needs_a_yes(self):
        code, text = self.ui([], self.reader(), answers=["2", SPOTIFY_URL, "n"])
        self.assertEqual((code, self.calls), (0, []))
        self.assertIn("Skipped.", text)
        self.assertTrue((self.tmp / "Playlists" / "lo-fi-beats.txt").is_file())

    def test_a_link_works_with_no_playlists_on_disk_at_all(self):
        # "no playlist .txt files" used to be a dead end before anything could be pasted
        for leftover in (self.tmp / "Playlists").glob("*.txt"):
            leftover.unlink()
        code, text = self.ui([], self.reader(), answers=["2", SPOTIFY_URL, "n"])
        self.assertEqual(code, 0)
        self.assertNotIn("No playlist .txt files", text)

    def test_enter_instead_of_a_link_cancels(self):
        code, text = self.ui([], self.reader(), answers=["2", ""])
        self.assertEqual((code, self.calls), (0, []))

    def test_rubbish_instead_of_a_link_is_said_plainly(self):
        code, text = self.ui([], self.reader(), answers=["2", "my playlist"])
        self.assertEqual((code, self.calls), (2, []))
        self.assertIn("Not a link this tool can read", text)

    def test_an_existing_file_can_be_kept_and_downloaded_as_it_is(self):
        self.playlist("Keep This | 1:00\n", name="lo-fi-beats")
        code, text = self.ui([], self.reader(), answers=["2", SPOTIFY_URL, "k", "y"])
        self.assertEqual(code, 0)
        self.assertIn("Keep This",
                      (self.tmp / "Playlists" / "lo-fi-beats.txt").read_text("utf-8"))
        self.assertEqual(self.calls, [["--only", "lo-fi-beats"]])

    def test_an_existing_file_can_be_replaced_from_the_link(self):
        self.playlist("Keep This | 1:00\n", name="lo-fi-beats")
        code, _ = self.ui([], self.reader(), answers=["2", SPOTIFY_URL, "r", "n"])
        self.assertEqual(code, 0)
        self.assertNotIn("Keep This",
                         (self.tmp / "Playlists" / "lo-fi-beats.txt").read_text("utf-8"))

    def test_a_scripted_run_never_sees_the_menu(self):
        # --only, --yes and --import are how a scheduled run works: no questions at all
        self.playlist("A - One | 1:00\n", name="mix")
        for argv in (["--only", "mix", "--yes"], ["--import", SPOTIFY_URL]):
            code, text = self.ui(argv, self.reader())
            self.assertNotIn("Where from?", text, argv)
