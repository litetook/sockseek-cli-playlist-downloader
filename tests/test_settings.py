"""Tests: config.yaml, the folders, and the configuration block in the log."""
from .support import *  # noqa: F403


class Config(unittest.TestCase):
    """config.yaml: a flat list of names and values, no comments in the file itself."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "config.yaml"
        self.warnings: list[str] = []

    def load(self):
        return sb.load_config(self.path, warn=self.warnings.append)

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")

    def parse_cli(self, *argv, config=None):
        """parse_args with stderr captured; a SystemExit is returned as its code."""
        with redirect_stderr(io.StringIO()) as err:
            try:
                return sb.parse_args(list(argv), config), err
            except SystemExit as exc:
                return exc.code, err

    # --- the file itself
    def test_missing_file_is_created_from_template(self):
        # a missing file is written from the template and read back, so the very first run
        # already uses exactly what is in the file
        self.assertTrue(self.load())
        self.assertTrue(self.path.exists())
        cfg = self.load()  # the generated template must be valid and warning-free
        self.assertEqual(self.warnings, [])
        self.assertEqual((cfg["length_tol_s"], cfg["retries"], cfg["playlist_timeout_min"]),
                         (45, 1, 10.0))
        self.assertEqual(set(cfg), {"length_tol_s", "retries", "playlist_timeout_min",
                                    "sockseek", "playlists", "output"})

    def test_the_file_carries_no_comments(self):
        # owner, 2026-10-11: the config must read like a list of values; explanations are in docs
        self.assertNotIn("#", sb.CONFIG_TEMPLATE)

    def test_shipped_config_is_the_template_itself(self):
        shipped = sb.APP_DIR / sb.CONFIG_NAME
        if not shipped.is_file():
            self.skipTest("no config.yaml in the app folder")
        self.assertEqual(shipped.read_text(encoding="utf-8"), sb.CONFIG_TEMPLATE)
        copy = self.dir / "shipped.yaml"  # a copy: the original is never touched
        shutil.copyfile(shipped, copy)
        self.assertEqual(sb.load_config(copy, warn=self.warnings.append),
                         {"length_tol_s": 45, "retries": 1, "playlist_timeout_min": 10.0,
                          "sockseek": "sockseek.exe", "playlists": "Playlists", "output": "output"})
        self.assertEqual(self.warnings, [])

    def test_config_does_not_mention_sockseek_only_options(self):
        for gone in ("stale_time_s", "fast_search", "strict", "desperate", "per_track",
                     "passes", "pause_s", "nested", "split_artist", "concurrent_searches",
                     "searches_per_time", "item_retries", "search_timeout_s", "remove_brackets",
                     "min_bitrate", "pref_format"):
            self.assertNotIn(gone, sb.CONFIG_TEMPLATE, gone)

    # --- the folders
    def test_folders_come_from_the_config_relative_to_the_app_folder(self):
        self.write("paths:\n  playlists: lists\n  output: D:\\music\n  sockseek: bin\\sockseek.exe\n")
        folders = sb.config_paths(self.load(), self.dir)
        self.assertEqual(folders["playlists"], self.dir / "lists")
        self.assertEqual(folders["sockseek"], self.dir / "bin" / "sockseek.exe")
        self.assertEqual(folders["output"], Path("D:\\music"))  # absolute stays absolute

    def test_folders_fall_back_to_the_layout_inside_the_project(self):
        folders = sb.config_paths({}, self.dir)
        self.assertEqual(folders, {"playlists": self.dir / "Playlists",
                                   "output": self.dir / "output",
                                   "sockseek": self.dir / "sockseek.exe"})

    def test_folder_sources_are_reported(self):
        args, _ = self.parse_cli(config={"output": "D:\\music"})
        self.assertEqual(args.sources["output"], "config")
        self.assertEqual(args.output, Path("D:\\music"))
        args, _ = self.parse_cli("--output", "X", config={"output": "D:\\music"})
        self.assertEqual((args.output, args.sources["output"]), (Path("X"), "cli"))
        args, _ = self.parse_cli()
        self.assertEqual(args.sources["playlists"], "default")

    # --- values
    def test_values_become_defaults_and_cli_overrides(self):
        self.write("search:\n  playlist_timeout_min: 90  # trailing comments are tolerated\n"
                   "  length_tol_s: 2\n")
        cfg = self.load()
        self.assertEqual((cfg["playlist_timeout_min"], cfg["length_tol_s"]), (90.0, 2))
        args, _ = self.parse_cli(config=cfg)
        self.assertEqual((args.playlist_timeout_min, args.length_tol_s), (90.0, 2))
        args, _ = self.parse_cli("--playlist-timeout", "30", config=cfg)
        self.assertEqual(args.playlist_timeout_min, 30.0)

    def test_quotes_and_flat_keys_are_accepted(self):
        self.write('retries: "3"\nlength_tol_s: 7\n')  # no section header at all
        self.assertEqual(self.load(), {"retries": 3, "length_tol_s": 7})

    def test_sources_cli_config_default(self):
        args, _ = self.parse_cli("--retries", "5", config={"length_tol_s": 6})
        self.assertEqual(args.sources["retries"], "cli")
        self.assertEqual(args.sources["length_tol_s"], "config")
        self.assertEqual(args.sources["playlist_timeout_min"], "default")
        self.assertEqual((args.retries, args.length_tol_s, args.playlist_timeout_min), (5, 6, 40.0))

    def test_length_tol_minus_one_is_legal_in_config_and_cli(self):
        self.write("search:\n  length_tol_s: -1\n")
        self.assertEqual(self.load()["length_tol_s"], -1)
        self.assertEqual(self.warnings, [])
        args, _ = self.parse_cli("--length-tol", "-1")
        self.assertEqual(args.length_tol_s, -1)

    def test_invalid_value_warns_and_falls_back_to_default(self):
        self.write("search:\n  length_tol_s: abc\n  retries: 4\n")
        cfg = self.load()
        self.assertNotIn("length_tol_s", cfg)
        self.assertEqual(cfg["retries"], 4)
        self.assertTrue(any("length_tol_s" in w and "default" in w for w in self.warnings), self.warnings)
        args, _ = self.parse_cli(config=cfg)
        self.assertEqual((args.length_tol_s, args.sources["length_tol_s"]), (45, "default"))

    def test_out_of_range_value_warns_and_falls_back(self):
        self.write("search:\n  retries: 0\n  playlist_timeout_min: -3\n  length_tol_s: -2\n")
        cfg = self.load()
        for key in ("retries", "playlist_timeout_min", "length_tol_s"):
            self.assertNotIn(key, cfg)
            self.assertTrue(any(key in w and "below the minimum" in w for w in self.warnings),
                            (key, self.warnings))
        args, _ = self.parse_cli(config=cfg)
        self.assertEqual((args.retries, args.playlist_timeout_min, args.length_tol_s), (2, 40.0, 45))

    def test_an_unknown_key_is_named_and_ignored(self):
        self.write("search:\n  retries: 3\n  min_bitrate: 256\n")
        cfg = self.load()
        self.assertEqual(cfg, {"retries": 3})
        self.assertTrue(any("min_bitrate" in w and "unknown" in w for w in self.warnings), self.warnings)

    def test_invalid_cli_value_exits_with_code_2(self):
        for argv in (["--length-tol", "abc"], ["--length-tol", "-2"],
                     ["--retries", "0"], ["--playlist-timeout", "-5"]):
            code, err = self.parse_cli(*argv)
            self.assertEqual(code, 2, argv)
            self.assertTrue(err.getvalue().strip(), argv)

    def test_out_of_range_value_message_names_the_key(self):
        code, err = self.parse_cli("--retries", "0")
        self.assertEqual(code, 2)
        self.assertIn("retries", err.getvalue())

    def test_deprecated_keys_still_load_and_warn(self):
        self.write("search:\n  tol: 2\n  timeout: 180\n")
        cfg = self.load()
        self.assertEqual(cfg, {"length_tol_s": 2, "playlist_timeout_min": 180.0})
        for old, new in (("tol", "length_tol_s"), ("timeout", "playlist_timeout_min")):
            self.assertTrue(any(f"'{old}' is deprecated" in w and f"'{new}'" in w for w in self.warnings),
                            (old, self.warnings))

    def test_broken_file_does_not_raise(self):
        self.write("not a config file [[[")
        self.assertEqual(self.load(), {})

    # --- migration from the old ini
    def test_the_old_ini_is_carried_over_once_and_set_aside(self):
        legacy = self.dir / "soulseek_batch.ini"
        legacy.write_text("[settings]\nlength_tol_s = 7\nretries = 3\nplaylist_timeout_min = 25\n",
                          encoding="utf-8")
        cfg = self.load()
        self.assertEqual((cfg["length_tol_s"], cfg["retries"], cfg["playlist_timeout_min"]),
                         (7, 3, 25.0))
        self.assertTrue(self.path.is_file())  # the new file now holds those values
        written = sb.load_config(self.path, warn=self.warnings.append)
        self.assertEqual((written["length_tol_s"], written["retries"], written["playlist_timeout_min"]),
                         (7, 3, 25.0))
        self.assertFalse(legacy.exists())  # kept, but out of the way
        self.assertTrue((self.dir / "soulseek_batch.ini.migrated").is_file())
        self.assertTrue(any("soulseek_batch.ini" in w and "config.yaml" in w for w in self.warnings),
                        self.warnings)

    def test_ffprobe_is_a_command_line_option_only(self):
        args, _ = self.parse_cli("--ffprobe", "X\\ffprobe.exe")
        self.assertEqual((args.ffprobe, args.sources["ffprobe"]), (Path("X\\ffprobe.exe"), "cli"))
        args, _ = self.parse_cli()
        self.assertEqual((args.ffprobe, args.sources["ffprobe"]), (None, "default"))
        self.assertIn("  ffprobe_path = auto [default]", sb.describe_config(args))

    def test_sockseek_args_string_is_split(self):
        args, _ = self.parse_cli('--sockseek-args=--mock-files-dir "C:\\a b\\mock" --no-config')
        self.assertEqual(args.sockseek_arg_list, ("--mock-files-dir", "C:\\a b\\mock", "--no-config"))


class ConfigReportInLog(AppCase):
    """Effective configuration: first lines of the log, with units in the key names and sources."""

    def run_dry(self, config_text):
        ini = self.tmp / "c.yaml"
        ini.write_text(config_text, encoding="utf-8")
        (self.tmp / "logs").mkdir()
        (self.tmp / "logs" / sb.SEQ_NAME).write_text("0\n", encoding="utf-8")  # a healthy counter: no rebuild WARN
        self.playlist(f"{LINE_A}\n")
        code, _, _ = self.main("--playlists", str(self.playlists), "--output", str(self.output),
                               "--config", str(ini), "--dry-run", "--retries", "5", "--length-tol", "-1")
        self.assertEqual(code, 0)
        return self.log_lines()

    def test_block_comes_first_with_units_and_sources(self):
        lines = self.run_dry("search:\n  timeout: 180\n  stale_time_s: 45\n")
        self.assertEqual(lines[0], "run #0001")  # the run number comes before the block
        self.assertTrue(lines[1].startswith("effective configuration"), lines[1])
        for expected in (
            "  length_tol_s = -1 [cli]",
            "  retries = 5 [cli]",
            "  playlist_timeout_min = 180 [config]",
            "  ffprobe_path = auto [default]",
            f"  playlists_dir = {self.playlists} [cli]",
            "  sockseek_exe = " + str(self.tmp / "sockseek.exe") + " [default]",
        ):
            self.assertIn(expected, lines)
        # every numeric key carries its unit in the name (or is a plain count)
        keys = [line.split(" = ")[0].strip() for line in lines if " = " in line and line.startswith("  ")]
        for key in ("length_tol_s", "playlist_timeout_min"):
            self.assertIn(key, keys)
        self.assertNotIn("tol", keys)
        self.assertNotIn("timeout", keys)
        # the whole block is short enough to read at a glance (paths + four settings + flags)
        self.assertLessEqual(len(keys), 10, keys)

    def test_deprecation_warning_follows_the_block(self):
        lines = self.run_dry("search:\n  timeout: 180\n")
        last_block_line = max(i for i, line in enumerate(lines) if line.startswith("  ") and " = " in line)
        warn = [i for i, line in enumerate(lines)
                if "'timeout' is deprecated" in line and "'playlist_timeout_min'" in line]
        self.assertEqual(len(warn), 1, lines)
        self.assertGreater(warn[0], last_block_line)  # the block stays the first thing in the log

    def test_out_of_range_config_value_warns_in_log_and_uses_default(self):
        # playlist_timeout_min: run_dry already overrides retries and length_tol on the command line
        lines = self.run_dry("search:\n  playlist_timeout_min: -3\n")
        self.assertTrue(any("playlist_timeout_min" in line and "below the minimum" in line
                            for line in lines), lines)
        self.assertIn("  playlist_timeout_min = 40 [default]", lines)

    def test_dry_run_command_has_length_tol_joined_with_equals(self):
        lines = self.run_dry("search:\n")
        command = [line for line in lines if line.startswith("dry run: ")][0]
        self.assertIn("--length-tol=-1", command)
        self.assertNotIn("--length-tol -1", command)


class SockseekConfOverride(unittest.TestCase):
    """sockseek.conf is published; sockseek.local.conf holds the login and overrides any key.

    sockseek reads exactly one config file and knows no includes, so the two are merged into
    work/sockseek.effective.conf and that file is what sockseek is pointed at.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.work = self.dir / "work"
        self.warnings: list[str] = []

    def conf(self, base, local=None):
        (self.dir / sb.SOCKSEEK_CONF).write_text(base, encoding="utf-8")
        if local is not None:
            (self.dir / sb.SOCKSEEK_LOCAL_CONF).write_text(local, encoding="utf-8")
        path = sb.effective_conf(self.dir, self.work, self.warnings.append)
        return path, path.read_text(encoding="utf-8")

    # --- merging
    def test_an_override_replaces_the_key_in_place(self):
        merged = sb.merge_conf("min-bitrate = 256\nfast-search = true\n", "min-bitrate = 320\n")
        self.assertEqual(merged, "min-bitrate = 320\nfast-search = true\n")

    def test_a_key_that_is_not_in_the_base_is_appended(self):
        merged = sb.merge_conf("min-bitrate = 256\n", "username = u\npassword = p\n")
        self.assertEqual(sb.parse_conf(merged),
                         {"min-bitrate": "256", "username": "u", "password": "p"})

    def test_comments_and_blank_lines_of_the_base_survive(self):
        merged = sb.merge_conf("# why 256\nmin-bitrate = 256\n", "min-bitrate = 320\n")
        self.assertIn("# why 256", merged)

    def test_a_profile_section_is_copied_untouched(self):
        base = "min-bitrate = 256\n\n[lossless]\nmin-bitrate = 900\n"
        merged = sb.merge_conf(base, "min-bitrate = 320\n")
        self.assertIn("[lossless]", merged)
        self.assertIn("min-bitrate = 900", merged)  # inside the profile, not rewritten
        self.assertEqual(sb.parse_conf(merged)["min-bitrate"], "320")

    # --- the login
    def test_a_missing_local_file_is_created_from_the_template(self):
        self.conf("min-bitrate = 256\n")
        local = self.dir / sb.SOCKSEEK_LOCAL_CONF
        self.assertTrue(local.is_file())
        self.assertEqual(local.read_text(encoding="utf-8"), sb.LOCAL_CONF_TEMPLATE)
        self.assertTrue(any(sb.SOCKSEEK_LOCAL_CONF in w for w in self.warnings), self.warnings)

    def test_the_login_reaches_the_effective_file_but_not_the_published_one(self):
        path, merged = self.conf("min-bitrate = 256\n", "username = u\npassword = p\n")
        self.assertEqual(path, self.work / sb.SOCKSEEK_EFFECTIVE_CONF)
        self.assertEqual(sb.parse_conf(merged)["password"], "p")
        self.assertNotIn("password", (self.dir / sb.SOCKSEEK_CONF).read_text(encoding="utf-8"))

    def test_the_warning_never_carries_the_values(self):
        self.conf("min-bitrate = 256\n")  # creates the template, warns about it
        self.assertFalse([w for w in self.warnings if "your-password" in w],
                         self.warnings)

    def test_missing_credentials_names_the_keys_that_are_not_set(self):
        self.assertEqual(sb.missing_credentials("username = u\npassword = p\n"), [])
        self.assertEqual(sb.missing_credentials("username = u\n"), ["password"])
        self.assertEqual(sb.missing_credentials(sb.LOCAL_CONF_TEMPLATE),
                         ["username", "password"])
        self.assertEqual(sb.missing_credentials(""), ["username", "password"])

    def test_the_shipped_conf_has_no_login_in_it(self):
        shipped = sb.APP_DIR / sb.SOCKSEEK_CONF
        if not shipped.is_file():
            self.skipTest("no sockseek.conf in the app folder")
        keys = sb.parse_conf(shipped.read_text(encoding="utf-8"))
        for key in sb.CREDENTIAL_KEYS:
            self.assertNotIn(key, keys)

    def test_min_bitrate_is_read_through_the_same_parser(self):
        path, _ = self.conf("min-bitrate = 256\n", "min-bitrate = 320\n")
        self.assertEqual(sb.read_min_bitrate(path), 320)  # the override wins


class LoginRequiredToRun(AppCase):
    """A run without a login stops with a message instead of failing inside sockseek."""

    def setUp(self):
        super().setUp()
        self.exe = self.tmp / "dummy.exe"
        self.exe.write_bytes(b"")
        self.playlist("A - One | 1:00\n")

    def test_placeholder_login_stops_the_run_and_names_the_file(self):
        (self.tmp / sb.SOCKSEEK_LOCAL_CONF).write_text(sb.LOCAL_CONF_TEMPLATE, encoding="utf-8")
        with mock.patch.object(sb_runner, "run_process") as spy:
            self.assertEqual(self.batch(dry_run=False, sockseek=self.exe), 2)
        spy.assert_not_called()  # sockseek is never started without a login
        text = self.log_text()
        self.assertIn("no Soulseek login", text)
        self.assertIn(sb.SOCKSEEK_LOCAL_CONF, text)

    def test_a_dry_run_still_works_without_a_login(self):
        (self.tmp / sb.SOCKSEEK_LOCAL_CONF).write_text(sb.LOCAL_CONF_TEMPLATE, encoding="utf-8")
        self.assertEqual(self.batch(dry_run=True, sockseek=self.exe), 0)

    def test_the_merged_config_is_what_sockseek_is_pointed_at(self):
        with mock.patch.object(sb_runner, "run_process", return_value=sb.OK) as spy:
            self.batch(dry_run=False, sockseek=self.exe)
        cmd = spy.call_args.args[0]
        self.assertEqual(Path(cmd[cmd.index("--config") + 1]),
                         self.tmp / "work" / sb.SOCKSEEK_EFFECTIVE_CONF)

    def test_a_caller_that_decides_about_the_config_is_left_alone(self):
        # --no-config is how the suite runs sockseek in mock mode: no config, no login needed
        with mock.patch.object(sb_runner, "run_process", return_value=sb.OK) as spy:
            self.batch(dry_run=False, sockseek=self.exe, sockseek_args=("--no-config",))
        cmd = spy.call_args.args[0]
        self.assertNotIn("--config", cmd)


class ThreeConfigLayers(unittest.TestCase):
    """sockseek.conf < sockseek.local.conf < --sockseek-conf. Each layer may hold as few
    keys as it likes; a key replaces the same key of a lower layer."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.work = self.dir / "work"
        self.warnings: list[str] = []
        (self.dir / sb.SOCKSEEK_CONF).write_text(
            "min-bitrate = 256\nfast-search = true\n", encoding="utf-8")
        (self.dir / sb.SOCKSEEK_LOCAL_CONF).write_text(
            "username = u\npassword = p\nmin-bitrate = 320\n", encoding="utf-8")

    def merged(self, extra=None):
        path = sb.effective_conf(self.dir, self.work, self.warnings.append, extra)
        return sb.parse_conf(path.read_text(encoding="utf-8"))

    def layer(self, text, name="extra.conf"):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_without_a_third_layer_the_local_file_wins(self):
        self.assertEqual(self.merged(),
                         {"min-bitrate": "320", "fast-search": "true",
                          "username": "u", "password": "p"})

    def test_the_command_line_layer_wins_over_both(self):
        keys = self.merged(self.layer("min-bitrate = 192\n"))
        self.assertEqual(keys["min-bitrate"], "192")
        self.assertEqual(keys["fast-search"], "true")  # untouched by the upper layers
        self.assertEqual(keys["username"], "u")        # the login still comes from the local file

    def test_a_layer_with_one_key_changes_only_that_key(self):
        keys = self.merged(self.layer("pref-format = flac\n"))
        self.assertEqual(keys["pref-format"], "flac")
        self.assertEqual(keys["min-bitrate"], "320")

    def test_the_layer_can_carry_a_different_login(self):
        keys = self.merged(self.layer("username = other\npassword = secret\n"))
        self.assertEqual((keys["username"], keys["password"]), ("other", "secret"))

    def test_a_layer_that_does_not_exist_is_simply_not_applied(self):
        keys = self.merged(self.dir / "nope.conf")
        self.assertEqual(keys["min-bitrate"], "320")

    def test_the_published_conf_declares_the_login_keys_commented_out(self):
        # sockseek refuses a key with an EMPTY value (measured 2026-10-11: "Error parsing
        # config ... at line 0"), so the two keys stay visible as comments instead
        shipped = sb.APP_DIR / sb.SOCKSEEK_CONF
        if not shipped.is_file():
            self.skipTest("no sockseek.conf in the app folder")
        text = shipped.read_text(encoding="utf-8")
        for key in sb.CREDENTIAL_KEYS:
            self.assertIn(f"# {key} =", text)
        self.assertEqual(sb.missing_credentials(text), list(sb.CREDENTIAL_KEYS))


class SockseekBinaryName(unittest.TestCase):
    """`sockseek.exe` on Windows, `sockseek` elsewhere: one config works on both."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_the_name_without_exe_is_used_when_that_is_what_exists(self):
        (self.dir / "sockseek").write_bytes(b"")
        self.assertEqual(sb.config_paths({}, self.dir)["sockseek"], self.dir / "sockseek")

    def test_the_exe_is_used_when_that_is_what_exists(self):
        (self.dir / "sockseek.exe").write_bytes(b"")
        self.assertEqual(sb.config_paths({}, self.dir)["sockseek"], self.dir / "sockseek.exe")

    def test_a_configured_name_without_exe_still_finds_the_exe(self):
        (self.dir / "bin").mkdir()
        (self.dir / "bin" / "sockseek.exe").write_bytes(b"")
        found = sb.config_paths({"sockseek": "bin/sockseek"}, self.dir)["sockseek"]
        self.assertEqual(found, self.dir / "bin" / "sockseek.exe")

    def test_nothing_there_leaves_the_configured_value_alone(self):
        found = sb.config_paths({"sockseek": "bin/sockseek.exe"}, self.dir)["sockseek"]
        self.assertEqual(found, self.dir / "bin" / "sockseek.exe")


class CommandLineConfigLayer(AppCase):
    """--sockseek-conf end to end."""

    def setUp(self):
        super().setUp()
        self.exe = self.tmp / "dummy.exe"
        self.exe.write_bytes(b"")
        self.playlist("A - One | 1:00\n")

    def test_the_layer_reaches_the_file_sockseek_is_given(self):
        extra = self.tmp / "lossless.conf"
        extra.write_text("pref-format = flac\n", encoding="utf-8")
        with mock.patch.object(sb_runner, "run_process", return_value=sb.OK) as spy:
            self.batch(dry_run=False, sockseek=self.exe, sockseek_conf=extra)
        cmd = spy.call_args.args[0]
        merged = Path(cmd[cmd.index("--config") + 1]).read_text(encoding="utf-8")
        self.assertEqual(sb.parse_conf(merged)["pref-format"], "flac")

    def test_a_missing_layer_file_stops_the_run(self):
        with mock.patch.object(sb_runner, "run_process") as spy:
            self.assertEqual(self.batch(dry_run=False, sockseek=self.exe,
                                        sockseek_conf=self.tmp / "nope.conf"), 2)
        spy.assert_not_called()
        self.assertIn("--sockseek-conf", self.log_text())

    def test_the_option_is_in_the_configuration_block(self):
        extra = self.tmp / "lossless.conf"
        extra.write_text("pref-format = flac\n", encoding="utf-8")
        args, _ = parse_cli_args("--sockseek-conf", str(extra))
        self.assertIn(f"  sockseek_conf = {extra} [cli]", sb.describe_config(args))


class ConfigParserDoesNotLoseValues(unittest.TestCase):
    """What the parser drops, it says out loud; and a `#` inside quotes is part of the value."""

    def test_a_line_without_a_space_after_the_colon_is_reported(self):
        warnings: list[str] = []
        self.assertEqual(sb.parse_yaml("retries:3\nlength_tol_s: 60\n", warnings.append),
                         {"length_tol_s": "60"})
        self.assertTrue(any("line 1" in w and "retries:3" in w for w in warnings), warnings)

    def test_a_section_header_is_not_reported_as_a_problem(self):
        warnings: list[str] = []
        sb.parse_yaml("paths:\n  output: x\n", warnings.append)
        self.assertEqual(warnings, [])

    def test_a_comment_is_not_a_problem_either(self):
        warnings: list[str] = []
        sb.parse_yaml("# just a note\nretries: 2\n", warnings.append)
        self.assertEqual(warnings, [])

    def test_a_hash_inside_quotes_stays_in_the_value(self):
        self.assertEqual(sb.parse_yaml('output: "D:/music#1"\n'), {"output": "D:/music#1"})
        self.assertEqual(sb.parse_yaml("output: 'D:/music#1'\n"), {"output": "D:/music#1"})

    def test_a_hash_outside_quotes_is_still_a_comment(self):
        self.assertEqual(sb.parse_yaml("retries: 2  # two attempts\n"), {"retries": "2"})

    def test_a_windows_path_keeps_its_drive_letter(self):
        self.assertEqual(sb.parse_yaml("output: D:\\music\n"), {"output": "D:\\music"})

    def test_the_run_log_names_the_line_it_could_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("search:\n  retries:3\n", encoding="utf-8")
            warnings: list[str] = []
            sb.load_config(path, warn=warnings.append)
        self.assertTrue(any("line 2" in w for w in warnings), warnings)


class MergeKeepsTheLoginOutOfProfiles(unittest.TestCase):
    """A new key must land BEFORE the first [profile], or it silently belongs to that profile."""

    def test_the_login_is_inserted_above_a_profile_section(self):
        base = "min-bitrate = 256\n\n[lossless]\nmin-bitrate = 900\n"
        merged = sb.merge_conf(base, "username = u\npassword = p\n")
        self.assertEqual(sb.missing_credentials(merged), [])     # parse_conf stops at "[",
        self.assertEqual(sb.parse_conf(merged)["username"], "u")  # so this is the real check
        self.assertLess(merged.index("username"), merged.index("[lossless]"))
        self.assertIn("min-bitrate = 900", merged)                # the profile is untouched

    def test_without_a_profile_nothing_changes_about_the_old_behaviour(self):
        merged = sb.merge_conf("min-bitrate = 256\n", "username = u\n")
        self.assertEqual(sb.parse_conf(merged), {"min-bitrate": "256", "username": "u"})


class FirstRunFiles(unittest.TestCase):
    """A fresh clone gets its three files, and a deleted one comes back from the template."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.warnings: list[str] = []

    def test_all_three_are_created_and_named(self):
        created = sb.ensure_files(self.dir, self.warnings.append)
        self.assertEqual(sorted(created), sorted([sb.CONFIG_NAME, sb.SOCKSEEK_CONF,
                                                  sb.SOCKSEEK_LOCAL_CONF]))
        for name in created:
            self.assertTrue((self.dir / name).is_file(), name)

    def test_the_login_file_gets_the_instruction_not_just_a_notice(self):
        sb.ensure_files(self.dir, self.warnings.append)
        self.assertTrue(any(sb.SOCKSEEK_LOCAL_CONF in w and "login" in w for w in self.warnings),
                        self.warnings)

    def test_a_file_that_is_there_is_left_alone(self):
        (self.dir / sb.CONFIG_NAME).write_text("search:\n  retries: 7\n", encoding="utf-8")
        created = sb.ensure_files(self.dir, self.warnings.append)
        self.assertNotIn(sb.CONFIG_NAME, created)
        self.assertEqual(sb.load_config(self.dir / sb.CONFIG_NAME)["retries"], 7)

    def test_a_deleted_sockseek_conf_comes_back_with_the_measured_values(self):
        # losing it silently would drop the 256 kbps floor and the 30 s wait from every run
        sb.ensure_files(self.dir, self.warnings.append)
        (self.dir / sb.SOCKSEEK_CONF).unlink()
        self.assertEqual(sb.ensure_files(self.dir, self.warnings.append), [sb.SOCKSEEK_CONF])
        text = (self.dir / sb.SOCKSEEK_CONF).read_text(encoding="utf-8")
        self.assertEqual(sb.read_min_bitrate(self.dir / sb.SOCKSEEK_CONF), 256)
        self.assertEqual(sb.parse_conf(text)["max-stale-time"], "30000")
        self.assertEqual(sb.missing_credentials(text), list(sb.CREDENTIAL_KEYS))

    def test_the_shipped_conf_is_the_template_itself(self):
        shipped = sb.APP_DIR / sb.SOCKSEEK_CONF
        if not shipped.is_file():
            self.skipTest("no sockseek.conf in the app folder")
        self.assertEqual(shipped.read_text(encoding="utf-8"), sb.SOCKSEEK_CONF_TEMPLATE)

    def test_a_run_through_the_engine_alone_still_gets_them(self):
        work = self.dir / "work"
        sb.effective_conf(self.dir, work, self.warnings.append)
        self.assertTrue((self.dir / sb.SOCKSEEK_LOCAL_CONF).is_file())
        self.assertTrue((self.dir / sb.SOCKSEEK_CONF).is_file())
