"""Shared fixtures for the test suite.

Imported with `from .support import *` by every test module, which is why the stdlib names and
the package aliases live here too: one place to look, no import block repeated nine times.
"""
import csv
import io
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import run
import soulseek as sb
from soulseek import batch as sb_batch
from soulseek import cli as sb_cli
from soulseek import quality as sb_quality
from soulseek import runner as sb_runner
from soulseek import settings as sb_settings

SOCKSEEK = sb.APP_DIR / "sockseek.exe"
HAVE_SOCKSEEK = SOCKSEEK.is_file()

# Mock "shared files" (content is irrelevant: --mock-files-no-read-tags skips tag reading).
MOCK_FILES = ("Alpha Band - First Song.mp3", "Beta Crew - Second Song.mp3", "Gamma Duo - Third Song.mp3")
# Playlist lines. Whole line is the search title (no --split-artist); the length is ignored
# because the tests pass length_tol=-1 (the mock derives synthetic lengths from file names).
LINE_A = "Alpha Band - First Song | 3:20"
LINE_B = "Beta Crew - Second Song | 3:20"
LINE_C = "Gamma Duo - Third Song | 3:20"
LINE_MISSING = "Missing Nowhere Track | 3:20"  # matches no mock file -> state=2 in the index
MOCK_ARG_NAMES = ("--mock-files-no-read-tags", "--no-config", "--no-listen", "--no-progress")
# With --mock-files-no-read-tags sockseek derives synthetic lengths from the file names, so its own
# length filter would reject the mock files. The script's --length-tol comes first on the command
# line and the LAST value wins inside sockseek, so this switches sockseek's filter off while the
# script's own ffprobe check keeps using the configured tolerance.
SOCKSEEK_LENGTH_OFF = ("--length-tol=-1",)
INDEX_HEADER = "filepath,artist,album,title,length,tracktype,state,failurereason\n"
MISSING_FFPROBE_WARN = "WARN ffprobe not found, skipping the length check, pass --ffprobe PATH"


def _find_tool(name: str):
    found = shutil.which(name)
    if found:
        return Path(found)
    fallback = Path(r"C:\ffmpeg\bin") / f"{name}.exe"
    return fallback if fallback.is_file() else None


FFMPEG, FFPROBE = _find_tool("ffmpeg"), _find_tool("ffprobe")
HAVE_FFMPEG = FFMPEG is not None and FFPROBE is not None
_SAMPLES: dict = {}


def sample_mp3(seconds: int = 30) -> Path:
    """A silent mp3 of a known duration made with the locally installed ffmpeg (cached per run)."""
    if seconds not in _SAMPLES:
        folder = tempfile.TemporaryDirectory()
        unittest.addModuleCleanup(folder.cleanup)
        target = Path(folder.name) / f"sample_{seconds}.mp3"
        subprocess.run([str(FFMPEG), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc",
                        "-t", str(seconds), "-q:a", "9", str(target)],
                       check=True, capture_output=True)
        _SAMPLES[seconds] = target
    return _SAMPLES[seconds]


REASON9 = "(no candidate passed the name/length/quality conditions)"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def parse_cli_args(*argv, config=None):
    """sb.parse_args with stderr captured; a SystemExit is returned as its code."""
    with redirect_stderr(io.StringIO()) as err:
        try:
            return sb.parse_args(list(argv), config), err
        except SystemExit as exc:
            return exc.code, err



class AppCase(unittest.TestCase):
    """Temp app folder with a Playlists dir; helpers to run run_batch / main and read results."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.playlists = self.tmp / "Playlists"
        self.playlists.mkdir()
        self.output = self.tmp / "output"
        self.out = ""
        # every real run has a login in sockseek.local.conf; without one the engine refuses
        # to start, which is its own test in test_settings
        (self.tmp / sb.SOCKSEEK_LOCAL_CONF).write_text(
            "username = test-login\npassword = test-password\n", encoding="utf-8")
        # a binary has to exist, or run.py's on-demand check would try to DOWNLOAD sockseek
        # (50 MB) in the middle of the suite - which is exactly what it did once
        (self.tmp / ("sockseek.exe" if sys.platform == "win32" else "sockseek")).write_bytes(b"")

    def playlist(self, text, name="mix"):
        (self.playlists / f"{name}.txt").write_text(text, encoding="utf-8")

    def batch(self, **kw):
        defaults = dict(
            app_dir=self.tmp, playlists_dir=self.playlists, output_dir=self.output,
            sockseek=self.tmp / "missing.exe", opts=sb.Options(length_tol=-1), dry_run=True,
            retries=1, timeout_min=1, explain=False,
            # a path that does not exist: the machine's ffprobe is not used unless a test asks for it
            ffprobe=self.tmp / "no-such-ffprobe.exe",
        )
        defaults.update(kw)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sb.run_batch(**defaults)
        self.out = buffer.getvalue()
        return code

    def main(self, *argv):
        """sb.main with APP_DIR pointed at the temp folder. Returns (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sb_settings, "APP_DIR", self.tmp), redirect_stdout(out), redirect_stderr(err):
            try:
                code = sb.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        self.out = out.getvalue()
        return code, out.getvalue(), err.getvalue()

    def run_logs(self) -> list[Path]:
        """The run logs of this temp app folder, oldest run number first."""
        return sorted((self.tmp / "logs").glob("run_*.log"))

    def log_text(self) -> str:
        return "".join(p.read_text(encoding="utf-8") for p in self.run_logs())

    @staticmethod
    def strip_stamp(text: str) -> list[str]:
        """Log lines without the '[HH:MM:SS] ' prefix."""
        return [line.split("] ", 1)[1] if line.startswith("[") else line for line in text.splitlines()]

    def log_lines(self) -> list[str]:
        """Lines of all run logs (a single run in most tests), without the time prefix."""
        return self.strip_stamp(self.log_text())

    def last_log_lines(self) -> list[str]:
        """Lines of the newest run log only."""
        return self.strip_stamp(self.run_logs()[-1].read_text(encoding="utf-8"))

    def failed_lines(self) -> list[str]:
        """Playlist part of every `FAILED  state=S reason=R  <line>` entry of the newest run log."""
        found = (re.fullmatch(r"FAILED  state=\S+ reason=\S+ \([^)]*\)  (.*)", line)
                 for line in self.last_log_lines())
        return [m.group(1) for m in found if m]

    def stray_failed_csv(self) -> list[Path]:
        """Any failed_*.csv anywhere under the temp app folder (there must be none)."""
        return sorted(self.tmp.rglob("failed_*"))


@unittest.skipUnless(HAVE_SOCKSEEK, "sockseek.exe is not in the app folder")
class MockBase(AppCase):
    """Whole batch against the real sockseek.exe in mock mode (no login, no network): setup and helpers."""

    def setUp(self):
        super().setUp()
        self.mock_dir = self.tmp / "mock"
        self.mock_dir.mkdir()
        for name in MOCK_FILES:
            (self.mock_dir / name).write_bytes(b"x" * 2000)
        # keep sockseek's console output out of the test report
        real_popen = subprocess.Popen

        def quiet_popen(cmd, **kw):
            kw.setdefault("stdout", subprocess.DEVNULL)
            kw.setdefault("stderr", subprocess.DEVNULL)
            return real_popen(cmd, **kw)

        patcher = mock.patch.object(subprocess, "Popen", quiet_popen)
        patcher.start()
        self.addCleanup(patcher.stop)

    def mock_args(self):
        return ("--mock-files-dir", str(self.mock_dir)) + MOCK_ARG_NAMES

    def real_batch(self, **kw):
        defaults = dict(dry_run=False, sockseek=SOCKSEEK, sockseek_args=self.mock_args())
        defaults.update(kw)
        return self.batch(**defaults)

    def audio_in(self, folder: Path):
        return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*.mp3"))
