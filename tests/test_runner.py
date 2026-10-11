"""Tests: the sockseek command line and the process around it."""
from .support import *  # noqa: F403


class BuildAndConvert(unittest.TestCase):
    def test_list_line_with_length(self):
        self.assertEqual(
            sb.build_list_line(sb.Track("A", "T", 249)),
            's:"artist=A, title=T, length=249"',
        )

    def test_list_line_without_length_or_artist(self):
        self.assertEqual(sb.build_list_line(sb.Track("", "T", None)), 's:"title=T"')

    def test_convert_collects_warnings(self):
        entries, warnings = sb.convert_playlist("A - One | 1:00\n# skip\n\nB - Two\n")
        self.assertEqual(len(entries), 2)
        self.assertIsInstance(entries[0], sb.Entry)
        self.assertEqual(entries[0].original, "A - One | 1:00")
        self.assertEqual(entries[0].list_line, 's:"title=A - One, length=60"')
        self.assertEqual(entries[0].track, sb.Track("", "A - One", 60))
        self.assertEqual(len(warnings), 1)
        self.assertIn("no valid length", warnings[0])

    def test_duplicate_lines_collapse_to_one_entry(self):
        # the third line differs in spelling but produces the same sockseek list line
        entries, warnings = sb.convert_playlist("A - One | 1:00\nB - Two | 2:00\nA - One | 1:00\nA - One | 60\n")
        self.assertEqual([e.original for e in entries], ["A - One | 1:00", "B - Two | 2:00"])
        self.assertTrue(any("2 duplicate line(s) dropped" in w for w in warnings), warnings)

    def cmd(self, **kw):
        return sb.build_command(Path("s.exe"), Path("l.txt"), Path("out"), sb.Options(**kw))

    def test_command_defaults(self):
        cmd = self.cmd()
        self.assertIn("--length-tol=3", cmd)
        self.assertNotIn("--length-tol", cmd)  # never the space-separated form
        self.assertEqual(cmd[cmd.index("--input-type") + 1], "list")
        # flat output: name format plus the index inside the playlist folder
        self.assertEqual(cmd[cmd.index("--name-format") + 1], sb.NAME_FORMAT)
        self.assertEqual(Path(cmd[cmd.index("--index-path") + 1]), Path("out") / "_index.csv")
        for absent in ("--print", "--verbose"):
            self.assertNotIn(absent, cmd)

    def test_sockseek_tuning_is_left_to_sockseek_conf(self):
        # these used to be ini keys this script forwarded; they are sockseek's own options now
        cmd = self.cmd()
        for absent in ("--max-stale-time", "--fast-search", "--max-retries", "--search-timeout",
                       "--searches-per-time", "--searches-renew-time", "--concurrent-searches",
                       "--strict-conditions", "--desperate", "--artist-maybe-wrong",
                       "--remove-brackets", "--remove-ft"):
            self.assertNotIn(absent, cmd)

    def test_length_tol_minus_one_is_joined_with_equals(self):
        cmd = self.cmd(length_tol=-1)
        self.assertIn("--length-tol=-1", cmd)
        self.assertNotIn("--length-tol", cmd)
        self.assertNotIn("-1", cmd)  # sockseek rejects "--length-tol -1"

    def test_the_length_window_is_the_only_condition_we_pass(self):
        args, _ = parse_cli_args()
        cmd = sb.build_command(Path("s.exe"), Path("l.txt"), Path("out"), sb.options_from_args(args))
        self.assertIn(f"--length-tol={args.length_tol_s}", cmd)

    def test_no_quality_option_is_ever_passed_by_us(self):
        # since 2026-10-11 every quality knob lives in sockseek.conf: the 256 kbps floor, the
        # format and bitrate preferences, and the hard maximum, which is simply not set at all
        # (unlimited). A value here would silently beat the file, which is what made
        # `pref-min-bitrate` in the conf dead before.
        for cmd in (self.cmd(), self.cmd(length_tol=-1, preview=True)):
            for gone in ("--min-bitrate", "--max-bitrate", "--pref-min-bitrate",
                         "--pref-max-bitrate", "--pref-format", "--strict-conditions"):
                self.assertFalse([a for a in cmd if a.startswith(gone)], (gone, cmd))

    def test_the_shipped_conf_keeps_the_floor_and_leaves_the_ceiling_open(self):
        conf = sb.APP_DIR / sb.SOCKSEEK_CONF
        if not conf.is_file():
            self.skipTest("no sockseek.conf in the app folder")
        keys = {}
        for line in conf.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                name, _, value = line.partition("=")
                keys[name.strip()] = value.strip()
        self.assertEqual(keys.get("min-bitrate"), "256")  # owner 2026-10-07: 256 is the floor
        self.assertNotIn("max-bitrate", keys)  # owner 2026-10-11: unlimited by default
        self.assertNotIn("strict-conditions", keys)  # would drop every standard client

    def test_verbose_log_and_extra_args_go_last(self):
        cmd = sb.build_command(Path("s.exe"), Path("l.txt"), Path("out"), log_file=Path("v.log"),
                               extra_args=("--no-config", "--no-listen"))
        self.assertEqual(cmd[cmd.index("--log-file") + 1], "v.log")
        self.assertIn("--verbose", cmd)
        self.assertEqual(cmd[-2:], ["--no-config", "--no-listen"])


class Processes(unittest.TestCase):
    def setUp(self):
        self.logs = []

    def run_py(self, code, retries=2, timeout=5):
        cmd = [sys.executable, "-c", code]
        return sb.run_with_retry(cmd, Path.cwd(), timeout, retries, self.logs.append, pause_s=0)

    def test_success(self):
        self.assertTrue(self.run_py("raise SystemExit(0)"))

    def test_failure_retries_then_stops(self):
        self.assertFalse(self.run_py("raise SystemExit(3)", retries=2))
        self.assertEqual(sum("attempt" in m for m in self.logs), 2)

    def test_timeout_kills_process(self):
        self.assertFalse(self.run_py("import time; time.sleep(30)", retries=1, timeout=1))
        self.assertTrue(any("timeout" in m for m in self.logs))

    def test_missing_executable(self):
        self.assertEqual(sb.run_process(["no-such-binary-xyz"], Path.cwd(), 5, self.logs.append), sb.ERROR)

    def test_run_process_statuses(self):
        run = lambda code, t=5: sb.run_process([sys.executable, "-c", code], Path.cwd(), t, self.logs.append)
        self.assertEqual(run("raise SystemExit(0)"), sb.OK)
        self.assertEqual(run("raise SystemExit(2)"), sb.FAILED)
        self.assertEqual(run("import time; time.sleep(30)", 1), sb.TIMEOUT)

    def test_ctrl_c_kills_child_and_is_reraised(self):
        proc = mock.Mock()
        proc.wait.side_effect = KeyboardInterrupt
        with mock.patch.object(sb_runner.subprocess, "Popen", return_value=proc), \
                mock.patch.object(sb_runner, "kill_tree") as kill:
            with self.assertRaises(KeyboardInterrupt):
                sb.run_process(["x"], Path.cwd(), 5, self.logs.append)
        kill.assert_called_once_with(proc)
