"""Tests: playlist files: lines, lengths, encodings."""
from .support import *  # noqa: F403


class ParseDuration(unittest.TestCase):
    def test_minutes_seconds(self):
        self.assertEqual(sb.parse_duration("4:09"), 249)

    def test_hours(self):
        self.assertEqual(sb.parse_duration("1:04:35"), 3875)

    def test_plain_seconds(self):
        self.assertEqual(sb.parse_duration("249"), 249)

    def test_fraction_is_rounded_not_truncated(self):
        self.assertEqual(sb.parse_duration("4.9"), 5)
        self.assertEqual(sb.parse_duration("4.4"), 4)
        self.assertEqual(sb.parse_duration("0:04.9"), 5)

    def test_invalid(self):
        for bad in ("", "abc", "4:", ":09", "1:2:3:4", "inf", "-5"):
            self.assertIsNone(sb.parse_duration(bad), bad)


class ParseLine(unittest.TestCase):
    def test_default_searches_whole_name(self):
        track = sb.parse_line("Nova Blue - Kate Ryan - Song (Remix) | 4:05")
        self.assertEqual(track, sb.Track("", "Nova Blue - Kate Ryan - Song (Remix)", 245))

    def test_blank_and_comment(self):
        self.assertIsNone(sb.parse_line("   "))
        self.assertIsNone(sb.parse_line("# comment | 1:00"))

    def test_uploader_prefix_is_kept(self):
        # proven on 2026-10-07 (runs #0004/#0005): sockseek finds the same files with or
        # without the SoundCloud uploader prefix, so the line is never rewritten
        track = sb.parse_line("Serafin - Katy Perry - Firework (Serafin Trance Edit) | 12:07")
        self.assertEqual(track.title, "Serafin - Katy Perry - Firework (Serafin Trance Edit)")
        self.assertEqual(track.artist, "")

    def test_commas_and_quotes_removed(self):
        self.assertEqual(sb.parse_line('Hello, "World" | 2:00').title, "Hello World")

    def test_no_length(self):
        self.assertIsNone(sb.parse_line("A - Song").length)

    def test_unicode_kept(self):
        self.assertEqual(sb.parse_line("Désenchantée | 3:00").title, "Désenchantée")

    def test_generated_files_are_not_playlists(self):
        self.assertTrue(sb.is_generated(Path("tracks_x.txt")))
        self.assertTrue(sb.is_generated(Path("mix.list.txt")))
        self.assertFalse(sb.is_generated(Path("mix.txt")))


class ReadPlaylist(unittest.TestCase):
    def read(self, data: bytes):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.txt"
            p.write_bytes(data)
            return sb.read_playlist(p)

    def test_utf8_with_bom(self):
        text, note = self.read("\ufeffПривіт | 1:00".encode("utf-8"))
        self.assertEqual(text, "Привіт | 1:00")
        self.assertIsNone(note)

    def test_cp1251_fallback_is_worded_as_a_guess(self):
        text, note = self.read("Привіт | 1:00".encode("cp1251"))
        self.assertEqual(text, "Привіт | 1:00")
        self.assertIn("not valid UTF-8", note)
        self.assertIn("decoded as cp1251", note)
        self.assertIn("check the file", note)

    def test_never_raises(self):
        text, note = self.read(bytes([0x98, 0x98, 0x20]))  # invalid in utf-8, unmapped in cp1251
        self.assertIsNotNone(note)
        self.assertIn("latin-1", note)
