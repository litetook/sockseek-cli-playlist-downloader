"""Settings of the tool itself: config.yaml, the folders, the tunable numbers.

Everything sockseek owns lives in sockseek.conf instead. Both files are documented in
docs/README.md, sections 5 and 7; the files themselves carry no comments.
"""
from __future__ import annotations

import configparser
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# The folder that holds config.yaml, the binaries, Playlists/ and output/: one level above
# this package, i.e. where run.py sits.
APP_DIR = Path(__file__).resolve().parent.parent

CONFIG_NAME = "config.yaml"
LEGACY_CONFIG_NAME = "soulseek_batch.ini"  # read once on upgrade, then renamed to *.migrated
SOCKSEEK_CONF = "sockseek.conf"              # the tuning, safe to publish
SOCKSEEK_LOCAL_CONF = "sockseek.local.conf"  # the login and any override; never committed
SOCKSEEK_EFFECTIVE_CONF = "sockseek.effective.conf"  # the two merged, written into work/

LOCAL_CONF_TEMPLATE = """\
username = your-soulseek-login
password = your-soulseek-password
"""

CREDENTIAL_KEYS = ("username", "password")

CONFIG_TEMPLATE = """\
paths:
  sockseek: sockseek.exe
  playlists: Playlists
  output: output

search:
  length_tol_s: 45
  retries: 1
  playlist_timeout_min: 10
"""

# sockseek.conf is recreated when it is missing, like config.yaml: it carries measured
# decisions (the 256 kbps floor, the 30 s wait, the lifted ranking cap), and losing them
# silently would quietly change every run. docs/README.md section 7 explains each key.
SOCKSEEK_CONF_TEMPLATE = """\
# username =
# password =

max-stale-time = 30000

min-bitrate = 256
pref-min-bitrate = 320
pref-max-bitrate = 1000000
pref-format = flac,wav,mp3

fast-search = true
fast-search-delay = 2000
fast-search-min-up-speed = 200
pref-strict-title = true
pref-strict-artist = true
"""

PATH_KEYS = ("sockseek", "playlists", "output")
PATH_DEFAULTS = {"sockseek": "sockseek.exe", "playlists": "Playlists", "output": "output"}


@dataclass(frozen=True)
class Setting:
    """One tunable number: config key (the unit is in the name), CLI flag, type, default,
    lowest legal value. All are numeric; a boolean one would need its own argparse action."""
    key: str
    flag: str
    kind: type
    default: object
    minimum: Optional[float]
    help: str
    old_keys: tuple[str, ...] = ()


SETTINGS: tuple[Setting, ...] = (
    Setting("length_tol_s", "--length-tol", int, 45, -1,
            "length tolerance in seconds around the playlist length; HARD condition, -1 disables (default 45)",
            ("tol",)),
    Setting("playlist_timeout_min", "--playlist-timeout", float, 40.0, 0,
            "wall-clock limit per attempt for one playlist, in minutes, 0 = none (default 40)",
            ("timeout",)),
    Setting("retries", "--retries", int, 2, 1, "attempts per playlist, at least 1 (default 2)"),
)
SETTING_BY_KEY = {s.key: s for s in SETTINGS}


def parse_yaml(text: str, warn: Optional[Callable[[str], None]] = None) -> dict:
    """Flat `key: value` pairs, section names ignored.

    Deliberately not a YAML implementation: the config is a list of names and values and the
    standard library has no YAML. Lists and deeper nesting are unsupported and surface as
    unknown keys in load_config. A line that looks like a setting but yields no pair is
    reported through `warn` with its number: dropping one silently is how a setting goes
    missing while the log still claims the default was chosen on purpose.
    """
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # split on the first ": ", not the first ":", or a value like a URL or a Windows path
        # would lose everything after its own colon
        head, sep, value = line.partition(": ")
        if not sep:
            head, value = line.rstrip(":"), ""
        key, value = head.strip(), _value(value)
        if key and value:
            values[key] = value
        elif (not key or not line.endswith(":")) and warn is not None:
            warn(f"line {number} is not a 'key: value' pair, ignored: {line!r}")
    return values


def _value(text: str) -> str:
    """One scalar: quotes stripped, and a trailing `# comment` removed only OUTSIDE quotes."""
    text = text.strip()
    for quote in ('"', "'"):
        if text.startswith(quote):
            closing = text.find(quote, 1)
            if closing > 0:
                return text[1:closing]
    return text.split("#", 1)[0].strip()


def check_value(setting: Setting, value: object) -> Optional[str]:
    """A message when the value is outside the legal range, else None."""
    if setting.minimum is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < setting.minimum:
            return f"{setting.key} = {value:g} is below the minimum {setting.minimum:g}"
    return None


def load_config(path: Path, warn: Optional[Callable[[str], None]] = None) -> dict:
    """config.yaml -> {setting or path key: value}.

    A missing file is written from the template, carrying over an old soulseek_batch.ini that
    still sits next to it. Invalid, out-of-range and unknown keys are named through `warn`
    and ignored, so a typo never silently changes a run.
    """
    if warn is None:
        def warn(message: str) -> None:
            print(message, file=sys.stderr)

    if not path.exists():
        return _create(path, warn)
    try:
        raw = parse_yaml(path.read_text(encoding="utf-8-sig"),
                         lambda message: warn(f"WARN: {path.name}: {message}"))
    except (OSError, UnicodeDecodeError) as exc:
        warn(f"WARN: cannot read {path.name}: {exc}")
        return {}
    values: dict = {}
    for key, text in raw.items():
        if key in PATH_KEYS:
            values[key] = text
            continue
        setting = SETTING_BY_KEY.get(key) or next((s for s in SETTINGS if key in s.old_keys), None)
        if setting is None:
            warn(f"WARN: {path.name}: unknown key '{key}', ignored")
            continue
        if key != setting.key:
            warn(f"WARN: {path.name}: key '{key}' is deprecated, use '{setting.key}' "
                 f"(same value, unit in the name)")
        try:
            value = setting.kind(text)
        except ValueError:
            warn(f"WARN: {path.name}: invalid value for '{key}', using the default")
            continue
        problem = check_value(setting, value)
        if problem:
            warn(f"WARN: {path.name}: {problem}, ignored (using the default)")
            continue
        values[setting.key] = value
    return values


def _create(path: Path, warn: Callable[[str], None]) -> dict:
    """Write the template (with the old ini's values if there is one) and read it back."""
    legacy = path.with_name(LEGACY_CONFIG_NAME)
    carried = _read_legacy_ini(legacy, warn) if legacy.is_file() else {}
    text = CONFIG_TEMPLATE
    for key, value in carried.items():
        text = re.sub(rf"^(\s*){key}: .*$", rf"\g<1>{key}: {value}", text, flags=re.M)
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        return {}
    if carried:
        kept = legacy.with_suffix(".ini.migrated")
        try:
            legacy.rename(kept)
        except OSError:
            pass
        warn(f"WARN: {legacy.name} is replaced by {path.name} "
             f"(values carried over: {', '.join(sorted(carried))}); "
             f"the old file is kept as {kept.name}")
    return load_config(path, warn)  # one code path produces the typed values


def _read_legacy_ini(path: Path, warn: Callable[[str], None]) -> dict:
    """The numbers of the old [settings] ini. Folders were not configurable back then."""
    parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError) as exc:
        warn(f"WARN: cannot read {path.name}: {exc}")
        return {}
    if not parser.has_section("settings"):
        return {}
    carried: dict = {}
    for setting in SETTINGS:
        for key in (setting.key, *setting.old_keys):
            if not parser.has_option("settings", key):
                continue
            try:
                value = setting.kind(parser.get("settings", key))
            except ValueError:
                break
            if check_value(setting, value) is None:
                carried[setting.key] = f"{value:g}" if isinstance(value, float) else str(value)
            break
    return carried


def config_paths(config: dict, app_dir: Optional[Path] = None) -> dict[str, Path]:
    """The three folders/files: config value or built-in default, relative to app_dir.

    app_dir is read at CALL time - a default argument would freeze APP_DIR at import and
    ignore a patched one (which is how a whole run is tested inside a temp folder).
    """
    app_dir = APP_DIR if app_dir is None else app_dir
    found: dict[str, Path] = {}
    for key in PATH_KEYS:
        path = Path(str(config.get(key) or PATH_DEFAULTS[key]))
        found[key] = path if path.is_absolute() else app_dir / path
    found["sockseek"] = _either_suffix(found["sockseek"])
    return found


def _either_suffix(exe: Path) -> Path:
    """`sockseek.exe` on Windows, `sockseek` elsewhere: whichever of the two is really there.

    One config file then works on both, instead of needing a different value per machine.
    """
    if exe.is_file():
        return exe
    other = exe.with_suffix("") if exe.suffix == ".exe" else exe.with_suffix(".exe")
    return other if other.is_file() else exe


def parse_conf(text: str) -> dict:
    """Top-level `key = value` pairs of a sockseek config. A [profile] section ends the scan:
    keys inside one do not apply to a plain run."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            break
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def merge_conf(base: str, override: str) -> str:
    """sockseek reads exactly one config file and knows no includes, so the two are merged
    here: a key present in the override replaces the one in the base, in place, and the rest
    is appended. Everything from the first [profile] section on is copied untouched."""
    extra = parse_conf(override)
    used: set[str] = set()
    out: list[str] = []
    tail: list[str] = []  # from the first [profile] on: copied untouched, nothing inserted
    for raw in base.splitlines():
        line = raw.strip()
        if tail or line.startswith("["):
            tail.append(raw)
            continue
        if not line.startswith("#") and "=" in line:
            key = line.partition("=")[0].strip()
            if key in extra:
                out.append(f"{key} = {extra[key]}")
                used.add(key)
                continue
        out.append(raw)
    rest = [f"{key} = {value}" for key, value in extra.items() if key not in used]
    if rest:
        # BEFORE the profiles, not after: a key appended past the first [section] would belong
        # to that profile, and parse_conf (which stops at "[") would never see it again - that
        # is how a correct sockseek.local.conf could read as "no login"
        out += ["", *rest]
    return "\n".join(out + ([""] + tail if tail else [])).rstrip() + "\n"


def missing_credentials(text: str) -> list[str]:
    """Which login keys are absent or still the template placeholder. Values are never
    returned or logged - only the names of the keys."""
    values = parse_conf(text)
    return [key for key in CREDENTIAL_KEYS
            if not values.get(key) or values[key].startswith("your-soulseek-")]


def ensure_files(app_dir: Path, warn: Optional[Callable[[str], None]] = None) -> list[str]:
    """Create the files a fresh clone needs, and name the ones that were created.

    All three are made here rather than deep inside a run: the first thing a new user should
    see is "put your login in this file", not an error after a 50 MB download.
    """
    if warn is None:
        def warn(message: str) -> None:
            print(message, file=sys.stderr)
    created: list[str] = []
    for name, text in ((CONFIG_NAME, CONFIG_TEMPLATE),
                       (SOCKSEEK_CONF, SOCKSEEK_CONF_TEMPLATE),
                       (SOCKSEEK_LOCAL_CONF, LOCAL_CONF_TEMPLATE)):
        path = app_dir / name
        if path.exists():
            continue
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            warn(f"WARN cannot create {name}: {exc}")
            continue
        created.append(name)
        if name == SOCKSEEK_LOCAL_CONF:
            warn(f"WARN created {name}: put your Soulseek login there "
                 f"(it is git-ignored and overrides {SOCKSEEK_CONF})")
        else:
            warn(f"WARN created {name} from the built-in template")
    return created


def effective_conf(app_dir: Path, work_dir: Path,
                   warn: Optional[Callable[[str], None]] = None,
                   extra: Optional[Path] = None) -> Path:
    """Merge the sockseek config layers into work/ and return that file.

    Lowest to highest: sockseek.conf (published defaults, no login) -> sockseek.local.conf
    (this machine: the login and anything else you want changed) -> the file given with
    --sockseek-conf. Each layer may hold as few keys as it likes; a key replaces the same key
    of a lower layer. sockseek reads exactly one file and has no `include`, which is why they
    are merged here instead.
    """
    if warn is None:
        def warn(message: str) -> None:
            print(message, file=sys.stderr)
    ensure_files(app_dir, warn)  # a run started through the engine alone still gets them
    local_path = app_dir / SOCKSEEK_LOCAL_CONF

    def text_of(path: Optional[Path]) -> str:
        if path is None or not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            warn(f"WARN cannot read {path.name}: {exc}")
            return ""

    merged = text_of(app_dir / SOCKSEEK_CONF)
    for layer in (local_path, extra):
        merged = merge_conf(merged, text_of(layer))
    target = work_dir / SOCKSEEK_EFFECTIVE_CONF
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(merged, encoding="utf-8")
    except OSError as exc:
        warn(f"WARN cannot write {target.name}: {exc}")
    return target


def read_min_bitrate(conf: Path) -> Optional[int]:
    """sockseek.conf -> the top-level min-bitrate, or None.

    That file also holds the Soulseek password, so this one number is the only thing ever
    read out of it. Keys inside a [profile] section do not apply to a plain run.
    """
    try:
        text = conf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    value = parse_conf(text).get("min-bitrate")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
