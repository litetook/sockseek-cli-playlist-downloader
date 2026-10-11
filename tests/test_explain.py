"""Tests: the conditionless search that explains every failure."""
from .support import *  # noqa: F403


class ExplainFailures(unittest.TestCase):
    """The output below is copied from run #0005 (real Soulseek, --print results, conditions off)."""

    PREVIEW = """Results for Paradisio - Bailando (Arman John Edit) (604s):
No results

Results for You Got The Love (Club Calimari Remix) (319s):

[346s/320kbps /13.2MB] DJ-Promo\\..\\The Source - You Got The Love (Club Calimari Remix).mp3
[346s/320kbps /13.2MB] DJ-Promo\\..\\Club Calimari - You Got The Love (Club Calimari Remix) 140.mp3
Total: 2


Results for Justin Timberlake - Sexy Back (SUITSIDE Edit) (267s):

[267s/320kbps /10.2MB] DJ-Promo\\..\\Justin Timberlake - Sexy Back (Suitside Edit).mp3
Total: 1
"""

    def test_parse_groups_candidates_by_title_and_keeps_empty_ones(self):
        found = sb.parse_preview(self.PREVIEW)
        self.assertEqual(len(found), 3)
        self.assertEqual(found["Paradisio - Bailando (Arman John Edit)"], [])
        two = found["You Got The Love (Club Calimari Remix)"]
        self.assertEqual([(c.length, c.bitrate) for c in two], [(346, 320), (346, 320)])
        self.assertIn("Club Calimari", two[1].path)

    def test_unknown_bitrate_does_not_break_the_parser(self):
        found = sb.parse_preview("Results for X (10s):\n\n[12s/?kbps /1.0MB] p\\q.mp3\nTotal: 1\n")
        self.assertEqual([(c.length, c.bitrate) for c in found["X"]], [(12, None)])

    def failure(self, length="319"):
        return {"playlist_line": "You Got The Love (Club Calimari Remix) | 5:19",
                "index_title": "You Got The Love (Club Calimari Remix)", "index_length": length,
                "state": "2", "failurereason": "9"}

    def test_an_empty_search_after_a_reason_4_failure_is_not_called_an_absence(self):
        # the index already said the run found and tried a candidate (reason 4), so an empty
        # extra search is a search that did not answer, not proof that nothing is shared
        failure = dict(self.failure(), failurereason="4")
        lines = sb.explain_failure(failure, [], 45, 256)
        text = " ".join(lines)
        self.assertIn("did not answer in time", text)
        self.assertNotIn("nothing on the network", text)

    def test_nothing_on_the_network_is_said_plainly(self):
        lines = sb.explain_failure(self.failure(), [], 3, 256)
        self.assertEqual(len(lines), 1)
        self.assertIn("nothing on the network", lines[0])

    def test_rejected_by_length_names_the_gap_and_the_flag(self):
        found = sb.parse_preview(self.PREVIEW)
        lines = sb.explain_failure(self.failure(), found["You Got The Love (Club Calimari Remix)"], 3, 256)
        text = " ".join(lines)
        self.assertIn("IS on the network", text)
        self.assertIn("346s/320kbps", text)
        self.assertIn("diff +27s", text)
        self.assertIn("--length-tol 28", text)  # 27 + 1, so the file fits next time

    def test_rejected_by_quality_names_the_floor_and_its_source(self):
        low = [sb.Candidate(319, 65, "p/q.opus")]
        lines = sb.explain_failure(self.failure(), low, 3, 256)
        text = " ".join(lines)
        self.assertIn("rejected by quality", text)
        self.assertIn("65kbps", text)
        self.assertIn("sockseek.conf", text)

    def test_fine_candidate_means_the_uploader_went_silent(self):
        fine = [sb.Candidate(319, 320, "p/q.mp3")]
        lines = sb.explain_failure(self.failure(), fine, 3, 256)
        self.assertIn("uploader did not deliver", " ".join(lines))

    def test_not_searched_is_not_reported_as_absent(self):
        # --no-explain must never turn into "nothing on the network": that is a different claim
        lines = sb.explain_failure(self.failure(), None, 3, 256)
        self.assertIn("not checked", lines[0])
        self.assertNotIn("nothing on the network", " ".join(lines))


class MinBitrateFromSockseekConf(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.conf = Path(self._tmp.name) / "sockseek.conf"

    def test_reads_the_global_value(self):
        self.conf.write_text("username = u\npassword = p\nmin-bitrate = 256\n", encoding="utf-8")
        self.assertEqual(sb.read_min_bitrate(self.conf), 256)

    def test_ignores_profiles_because_a_plain_run_does_not_use_them(self):
        self.conf.write_text("min-bitrate = 256\n[lossless]\nmin-bitrate = 900\n", encoding="utf-8")
        self.assertEqual(sb.read_min_bitrate(self.conf), 256)
        self.conf.write_text("[lossless]\nmin-bitrate = 900\n", encoding="utf-8")
        self.assertIsNone(sb.read_min_bitrate(self.conf))

    def test_missing_file_or_junk_value_is_simply_unknown(self):
        self.assertIsNone(sb.read_min_bitrate(self.conf))  # not created
        self.conf.write_text("min-bitrate = soon\n", encoding="utf-8")
        self.assertIsNone(sb.read_min_bitrate(self.conf))

    def test_the_shipped_conf_carries_the_floor_the_owner_asked_for(self):
        # owner, 2026-10-07 13:08: "256 kb is the baseline minimum"
        shipped = sb.APP_DIR / sb.SOCKSEEK_CONF
        if shipped.is_file():
            self.assertEqual(sb.read_min_bitrate(shipped), 256)
