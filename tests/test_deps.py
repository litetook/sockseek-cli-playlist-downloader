"""Tests: the pinned external tools - resolving, downloading, verifying, installing."""
import hashlib
import io
import tarfile
import zipfile

from soulseek import deps

from .support import *  # noqa: F403


class FakeResponse(io.BytesIO):
    """Just enough of what urlopen returns: a context manager that reads bytes."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def served(payload: bytes):
    """A urlopen stand-in that always answers with these bytes."""
    def urlopen(url, timeout=None):
        return FakeResponse(payload)
    return urlopen


def zipped(name: str, payload: bytes, folder: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(folder + name, payload)
    return buffer.getvalue()


def tarred(name: str, payload: bytes, folder: str = "") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
        info = tarfile.TarInfo(folder + name)
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


class ToolPlan(unittest.TestCase):
    """dependencies.yaml -> what to fetch for this machine."""

    CONFIG = {
        "sockseek.version": "3.0.5",
        "sockseek.url": "https://example.com/v{version}/{asset}",
        "sockseek.windows.asset": "sockseek_{version}_win-x64.zip",
        "sockseek.windows.member": "sockseek.exe",
        "sockseek.windows.sha256": "a" * 64,
        "sockseek.macos-arm64.asset": "sockseek_{version}_osx-arm64.tar.gz",
        "sockseek.macos-arm64.member": "sockseek",
        "sockseek.macos-arm64.sha256": "b" * 64,
        "yt-dlp.version": "2026.08.19",
        "yt-dlp.url": "https://example.com/{version}/{asset}",
        "yt-dlp.windows.asset": "yt-dlp.exe",
        "yt-dlp.windows.sha256": "c" * 64,
    }

    def test_the_version_is_substituted_into_the_asset_and_the_url(self):
        sockseek = deps.tools(self.CONFIG, Path("/app"), "windows")[0]
        self.assertEqual(sockseek.url,
                         "https://example.com/v3.0.5/sockseek_3.0.5_win-x64.zip")
        self.assertEqual(sockseek.sha256, "a" * 64)

    def test_an_archive_is_recognised_by_having_a_member(self):
        windows = {t.name: t for t in deps.tools(self.CONFIG, Path("/app"), "windows")}
        self.assertTrue(windows["sockseek"].archive)      # a zip to unpack
        self.assertFalse(windows["yt-dlp"].archive)       # the download IS the binary

    def test_the_binary_lands_next_to_the_tool(self):
        windows = {t.name: t for t in deps.tools(self.CONFIG, Path("/app"), "windows")}
        self.assertEqual(windows["sockseek"].target, Path("/app/sockseek.exe"))
        self.assertEqual(windows["yt-dlp"].target, Path("/app/yt-dlp.exe"))

    def test_each_platform_gets_its_own_asset(self):
        mac = {t.name: t for t in deps.tools(self.CONFIG, Path("/app"), "macos-arm64")}
        self.assertTrue(mac["sockseek"].url.endswith("osx-arm64.tar.gz"))
        self.assertEqual(mac["sockseek"].target, Path("/app/sockseek"))  # no .exe

    def test_a_platform_that_is_not_pinned_yields_nothing(self):
        self.assertEqual(deps.tools(self.CONFIG, Path("/app"), "linux-arm"), [])

    def test_this_machine_resolves_to_a_known_platform(self):
        self.assertIn(deps.platform_key(),
                      ("windows", "macos-arm64", "macos-x64", "linux-x64", "linux-arm"))


class Installing(unittest.TestCase):
    """Download, verify, unpack. The checksum decides whether anything is written."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.log: list[str] = []

    def tool(self, payload, member=None, name="t.bin", sha=None):
        return deps.Tool(name="toolname", version="1.2.3",
                         url=f"https://example.com/{name}",
                         sha256=sha or hashlib.sha256(payload).hexdigest(),
                         member=member, target=self.dir / "toolname.exe")

    def test_a_plain_binary_is_written_as_it_is(self):
        payload = b"binary-content"
        tool = self.tool(payload)
        with mock.patch.object(deps.urllib.request, "urlopen", served(payload)):
            self.assertTrue(deps.install(tool, self.log.append))
        self.assertEqual(tool.target.read_bytes(), payload)
        self.assertTrue(any("sha256 ok" in line for line in self.log), self.log)

    def test_a_wrong_checksum_installs_nothing(self):
        payload = b"binary-content"
        tool = self.tool(payload, sha="d" * 64)
        with mock.patch.object(deps.urllib.request, "urlopen", served(payload)):
            self.assertFalse(deps.install(tool, self.log.append))
        self.assertFalse(tool.target.exists())  # nothing half-written is left behind
        self.assertTrue(any("checksum mismatch" in line for line in self.log), self.log)

    def test_the_member_is_taken_out_of_a_zip(self):
        payload = zipped("sockseek.exe", b"the-binary")
        tool = self.tool(payload, member="sockseek.exe", name="t.zip")
        with mock.patch.object(deps.urllib.request, "urlopen", served(payload)):
            self.assertTrue(deps.install(tool, self.log.append))
        self.assertEqual(tool.target.read_bytes(), b"the-binary")

    def test_a_member_inside_a_sub_folder_is_still_found(self):
        # a release that starts packing into a folder must not break the install
        payload = zipped("sockseek.exe", b"the-binary", folder="sockseek_3.0.5/")
        tool = self.tool(payload, member="sockseek.exe", name="t.zip")
        with mock.patch.object(deps.urllib.request, "urlopen", served(payload)):
            self.assertTrue(deps.install(tool, self.log.append))
        self.assertEqual(tool.target.read_bytes(), b"the-binary")

    def test_a_tar_gz_works_the_same_way(self):
        payload = tarred("sockseek", b"mac-binary", folder="dist/")
        tool = self.tool(payload, member="sockseek", name="t.tar.gz")
        with mock.patch.object(deps.urllib.request, "urlopen", served(payload)):
            self.assertTrue(deps.install(tool, self.log.append))
        self.assertEqual(tool.target.read_bytes(), b"mac-binary")

    def test_a_missing_member_is_an_error_not_an_empty_file(self):
        payload = zipped("something-else.exe", b"x")
        tool = self.tool(payload, member="sockseek.exe", name="t.zip")
        with mock.patch.object(deps.urllib.request, "urlopen", served(payload)):
            self.assertFalse(deps.install(tool, self.log.append))
        self.assertFalse(tool.target.exists())

    def test_a_download_that_fails_says_so_and_writes_nothing(self):
        def broken(url, timeout=None):
            raise OSError("no network")
        tool = self.tool(b"x")
        with mock.patch.object(deps.urllib.request, "urlopen", broken):
            self.assertFalse(deps.install(tool, self.log.append))
        self.assertFalse(tool.target.exists())
        self.assertTrue(any("download failed" in line for line in self.log), self.log)


class Ensure(unittest.TestCase):
    """ensure(): nothing happens when the tool is already there; a question guards a download."""

    CONFIG = {
        "yt-dlp.version": "1.0",
        "yt-dlp.url": "https://example.com/{version}/{asset}",
        "yt-dlp.windows.asset": "yt-dlp.exe",
        "yt-dlp.windows.sha256": hashlib.sha256(b"payload").hexdigest(),
        "yt-dlp.macos-arm64.asset": "yt-dlp_macos",
        "yt-dlp.macos-arm64.sha256": hashlib.sha256(b"payload").hexdigest(),
        "yt-dlp.macos-x64.asset": "yt-dlp_macos",
        "yt-dlp.macos-x64.sha256": hashlib.sha256(b"payload").hexdigest(),
        "yt-dlp.linux-x64.asset": "yt-dlp",
        "yt-dlp.linux-x64.sha256": hashlib.sha256(b"payload").hexdigest(),
        "yt-dlp.linux-arm.asset": "yt-dlp",
        "yt-dlp.linux-arm.sha256": hashlib.sha256(b"payload").hexdigest(),
    }

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.log: list[str] = []
        self.binary = deps.tools(self.CONFIG, self.dir)[0].target

    def test_an_installed_tool_is_returned_without_touching_the_network(self):
        self.binary.write_bytes(b"already here")
        def forbidden(url, timeout=None):
            raise AssertionError("must not download")
        with mock.patch.object(deps.urllib.request, "urlopen", forbidden):
            found = deps.ensure("yt-dlp", self.log.append, self.CONFIG, self.dir)
        self.assertEqual(found, self.binary)

    def test_a_refused_question_downloads_nothing(self):
        def forbidden(url, timeout=None):
            raise AssertionError("must not download")
        with mock.patch.object(deps.urllib.request, "urlopen", forbidden):
            found = deps.ensure("yt-dlp", self.log.append, self.CONFIG, self.dir,
                                ask=lambda question: False)
        self.assertIsNone(found)
        self.assertFalse(self.binary.exists())

    def test_an_accepted_question_installs_the_pinned_version(self):
        asked: list[str] = []
        with mock.patch.object(deps.urllib.request, "urlopen", served(b"payload")):
            found = deps.ensure("yt-dlp", self.log.append, self.CONFIG, self.dir,
                                ask=lambda question: asked.append(question) or True)
        self.assertEqual(found, self.binary)
        self.assertEqual(self.binary.read_bytes(), b"payload")
        self.assertTrue(any("1.0" in question for question in asked), asked)

    def test_a_tool_that_is_not_pinned_is_named_in_a_warning(self):
        self.assertIsNone(deps.ensure("ffmpeg", self.log.append, self.CONFIG, self.dir))
        self.assertTrue(any("ffmpeg" in line for line in self.log), self.log)

    def test_status_says_ok_or_missing(self):
        self.assertEqual([state for _, state in deps.status(self.CONFIG, self.dir)], ["missing"])
        self.binary.write_bytes(b"x")
        self.assertEqual([state for _, state in deps.status(self.CONFIG, self.dir)], ["ok"])


class PythonPackages(unittest.TestCase):
    """The same file can pin Python packages; none so far, but the mechanism is live."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.log: list[str] = []

    def test_nothing_pinned_means_nothing_runs(self):
        def forbidden(*a, **kw):
            raise AssertionError("pip must not run")
        with mock.patch.object(deps.subprocess, "run", forbidden):
            self.assertTrue(deps.ensure_python_packages({}, self.dir, self.log.append))

    def test_a_pinned_package_is_installed_into_vendor(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        config = {"python.packages": "requests==2.32.3, chardet==5.2.0"}
        with mock.patch.object(deps.subprocess, "run", fake_run):
            self.assertTrue(deps.ensure_python_packages(config, self.dir, self.log.append))
        self.assertEqual(len(calls), 1)
        cmd = calls[0]
        self.assertIn("--target", cmd)
        self.assertEqual(Path(cmd[cmd.index("--target") + 1]), self.dir / deps.VENDOR_DIR)
        self.assertIn("requests==2.32.3", cmd)
        self.assertIn(str(self.dir / deps.VENDOR_DIR), sys.path)

    def test_a_failing_pip_is_reported_not_raised(self):
        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, "", "no such package")

        with mock.patch.object(deps.subprocess, "run", fake_run):
            self.assertFalse(deps.ensure_python_packages({"python.packages": "nope==1"},
                                                         self.dir, self.log.append))
        self.assertTrue(any("pip failed" in line for line in self.log), self.log)


class ShippedDependencies(unittest.TestCase):
    """The file in this repository has to be complete, or a fresh clone cannot set itself up."""

    def setUp(self):
        self.config = deps.load(sb.APP_DIR / deps.DEPENDENCIES_NAME)
        if not self.config:
            self.skipTest(f"no {deps.DEPENDENCIES_NAME} in the app folder")

    def test_every_platform_is_pinned_for_every_tool(self):
        for key in ("windows", "macos-arm64", "macos-x64", "linux-x64", "linux-arm"):
            names = {tool.name for tool in deps.tools(self.config, Path("/app"), key)}
            self.assertEqual(names, set(deps.TOOL_NAMES), key)

    def test_every_checksum_looks_like_a_sha256(self):
        for key, value in self.config.items():
            if key.endswith(".sha256"):
                self.assertRegex(value, r"^[0-9a-f]{64}$", key)

    def test_the_urls_point_at_github_releases(self):
        for name in deps.TOOL_NAMES:
            self.assertRegex(self.config[f"{name}.url"],
                             r"^https://github\.com/[\w.-]+/[\w.-]+/releases/download/")

    def test_the_versions_are_plain_numbers(self):
        for name in deps.TOOL_NAMES:
            self.assertRegex(self.config[f"{name}.version"], r"^[\d.]+$", name)


class NeverHalfABinary(unittest.TestCase):
    """A failed unpack must leave nothing that later counts as installed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.log: list[str] = []

    def test_a_failed_extract_leaves_no_file_and_no_part_file(self):
        payload = zipped("other.exe", b"x")
        tool = deps.Tool(name="t", version="1", url="https://example.com/t.zip",
                         sha256=hashlib.sha256(payload).hexdigest(),
                         member="sockseek.exe", target=self.dir / "sockseek.exe")
        with mock.patch.object(deps.urllib.request, "urlopen", served(payload)):
            self.assertFalse(deps.install(tool, self.log.append))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), [])

    def test_a_good_install_leaves_only_the_binary(self):
        payload = zipped("sockseek.exe", b"real")
        tool = deps.Tool(name="t", version="1", url="https://example.com/t.zip",
                         sha256=hashlib.sha256(payload).hexdigest(),
                         member="sockseek.exe", target=self.dir / "sockseek.exe")
        with mock.patch.object(deps.urllib.request, "urlopen", served(payload)):
            self.assertTrue(deps.install(tool, self.log.append))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["sockseek.exe"])
