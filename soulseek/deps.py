"""The external tools this one drives, at pinned versions.

`dependencies.yaml` is the single source of truth: a version, a file name and a sha256 per
platform. The same code serves both `setup.py` (install everything now) and the run itself
(a tool is missing, fetch exactly that one), so it makes no difference to the user whether
they ran setup first.

Nothing is installed system-wide and nothing is run as administrator: the binaries land next
to the tool, Python packages (none so far) land in `vendor/`.
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import settings

DEPENDENCIES_NAME = "dependencies.yaml"
VENDOR_DIR = "vendor"
TOOL_NAMES = ("sockseek", "yt-dlp")
DOWNLOAD_TIMEOUT_S = 300
CHUNK = 1 << 16


@dataclass(frozen=True)
class Tool:
    """One pinned external tool for this machine."""
    name: str
    version: str
    url: str
    sha256: str
    member: Optional[str]  # file to take out of an archive; None = the download is the binary
    target: Path

    @property
    def archive(self) -> bool:
        return self.member is not None

    def present(self) -> bool:
        return self.target.is_file()


def platform_key() -> str:
    """windows | macos-arm64 | macos-x64 | linux-x64 | linux-arm."""
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64") or machine.startswith("armv")
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos-arm64" if arm else "macos-x64"
    return "linux-arm" if arm else "linux-x64"


def bundled(name: str) -> Optional[Path]:
    """The copy inside a frozen build (PyInstaller unpacks data into sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / name if base else None


def load(path: Optional[Path] = None) -> dict:
    """dependencies.yaml as flat dotted keys (`sockseek.windows.sha256`).

    A file next to the tool wins, so the pins can be edited without rebuilding; the copy
    baked into a frozen build is the fallback, so a single downloaded .exe still knows what
    to fetch.
    """
    path = path or settings.APP_DIR / DEPENDENCIES_NAME
    if not path.is_file():
        inside = bundled(DEPENDENCIES_NAME)
        if inside and inside.is_file():
            path = inside
    try:
        return settings.parse_yaml(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError):
        return {}


def tools(config: dict, app_dir: Optional[Path] = None, key: Optional[str] = None) -> list[Tool]:
    """Every pinned tool for this platform, with where its binary belongs."""
    app_dir = settings.APP_DIR if app_dir is None else app_dir
    key = key or platform_key()
    found: list[Tool] = []
    for name in TOOL_NAMES:
        version = config.get(f"{name}.version")
        asset = config.get(f"{name}.{key}.asset")
        sha256 = config.get(f"{name}.{key}.sha256")
        url = config.get(f"{name}.url")
        if not (version and asset and sha256 and url):
            continue
        asset = asset.format(version=version)
        member = config.get(f"{name}.{key}.member")
        binary = member or asset
        found.append(Tool(name=name, version=version,
                          url=url.format(version=version, asset=asset),
                          sha256=sha256, member=member, target=app_dir / binary))
    return found


def find(name: str, config: dict, app_dir: Optional[Path] = None) -> Optional[Tool]:
    for tool in tools(config, app_dir):
        if tool.name == name:
            return tool
    return None


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            sha.update(block)
    return sha.hexdigest()


def download(url: str, target: Path, log: Callable[[str], None]) -> bool:
    """Fetch url into target. Returns False with a message instead of raising."""
    log(f"downloading {url}")
    try:
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_S) as response:
            with target.open("wb") as fh:
                while True:
                    block = response.read(CHUNK)
                    if not block:
                        break
                    fh.write(block)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        log(f"ERROR download failed: {exc}")
        return False
    return True


def extract(archive: Path, member: str, target: Path, log: Callable[[str], None]) -> bool:
    """Take the one file whose name ends with `member` out of a .zip or .tar.gz.

    The layout inside the archive is not assumed: whatever matches by name is taken, so a
    release that starts packing into a sub-folder does not break this.
    """
    try:
        if archive.suffix == ".zip" or zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as zf:
                names = [n for n in zf.namelist() if n.rstrip("/").endswith(member)]
                if not names:
                    log(f"ERROR {member} is not in {archive.name}")
                    return False
                with zf.open(names[0]) as src, target.open("wb") as dst:
                    dst.write(src.read())
            return True
        with tarfile.open(archive) as tf:
            names = [n for n in tf.getnames() if n.endswith(member)]
            if not names:
                log(f"ERROR {member} is not in {archive.name}")
                return False
            src = tf.extractfile(names[0])
            if src is None:
                log(f"ERROR {member} in {archive.name} is not a file")
                return False
            with src, target.open("wb") as dst:
                dst.write(src.read())
        return True
    except (zipfile.BadZipFile, tarfile.TarError, OSError) as exc:
        log(f"ERROR cannot unpack {archive.name}: {exc}")
        return False


def install(tool: Tool, log: Callable[[str], None]) -> bool:
    """Download, verify the pinned sha256, unpack if needed, make it executable.

    The checksum is verified BEFORE the file is put in place, so a truncated or tampered
    download never becomes the binary this tool runs.
    """
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / Path(tool.url).name
        if not download(tool.url, raw, log):
            return False
        got = digest(raw)
        if got != tool.sha256:
            log(f"ERROR checksum mismatch for {raw.name}: expected {tool.sha256}, got {got}")
            return False
        log(f"sha256 ok ({tool.name} {tool.version})")
        try:
            tool.target.parent.mkdir(parents=True, exist_ok=True)
            if tool.archive:
                if not extract(raw, tool.member or "", tool.target, log):
                    return False
            else:
                tool.target.write_bytes(raw.read_bytes())
        except OSError as exc:
            log(f"ERROR cannot write {tool.target}: {exc}")
            return False
    if sys.platform != "win32":
        try:
            tool.target.chmod(0o755)
        except OSError:
            pass
    log(f"installed {tool.name} {tool.version} -> {tool.target}")
    return True


def ensure(name: str, log: Callable[[str], None], config: Optional[dict] = None,
           app_dir: Optional[Path] = None,
           ask: Optional[Callable[[str], bool]] = None) -> Optional[Path]:
    """The path to `name`, installing the pinned version if it is not there yet.

    `ask` is called before a download (so a run can refuse to pull 50 MB unasked); without
    it the download just happens, which is what `setup.py --yes` and a scheduled run want.
    """
    config = load() if config is None else config
    tool = find(name, config, app_dir)
    if tool is None:
        log(f"WARN {name} is not pinned in {DEPENDENCIES_NAME}")
        return None
    if tool.present():
        return tool.target
    if ask is not None and not ask(f"{tool.name} {tool.version} is missing. Download it?"):
        return None
    return tool.target if install(tool, log) else None


def status(config: Optional[dict] = None, app_dir: Optional[Path] = None) -> list[tuple[Tool, str]]:
    """Every pinned tool with "ok" or "missing", for `setup.py --check`."""
    config = load() if config is None else config
    return [(tool, "ok" if tool.present() else "missing")
            for tool in tools(config, app_dir)]


def python_packages(config: dict) -> list[str]:
    """`python.packages` from the file: pinned `name==version` entries, comma separated.

    Empty so far - this tool uses the standard library only. The mechanism exists so that
    adding one later is a line in dependencies.yaml rather than a README instruction.
    """
    raw = config.get("python.packages") or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def ensure_python_packages(config: Optional[dict] = None, app_dir: Optional[Path] = None,
                          log: Callable[[str], None] = print) -> bool:
    """Install the pinned Python packages into vendor/ and put it on sys.path.

    vendor/ instead of the system or a venv: nothing outside this folder is touched, and a
    frozen build keeps working because vendor/ sits next to the executable.
    """
    config = load() if config is None else config
    wanted = python_packages(config)
    if not wanted:
        return True
    app_dir = settings.APP_DIR if app_dir is None else app_dir
    vendor = app_dir / VENDOR_DIR
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    missing = [spec for spec in wanted
               if not (vendor / spec.split("==")[0].replace("-", "_")).exists()]
    if not missing:
        return True
    log(f"installing {len(missing)} Python package(s) into {vendor}")
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(vendor), *missing]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"ERROR pip did not run: {exc}")
        return False
    if done.returncode != 0:
        log(f"ERROR pip failed: {(done.stderr or done.stdout or '').strip().splitlines()[-1:]}")
        return False
    log("Python packages ready")
    return True
