"""The engine's command line. The everyday entry point is run.py, which calls main() here."""
from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from typing import Optional

from . import __version__, settings
from .batch import run_batch
from .runner import Options
from .settings import PATH_KEYS, SETTINGS, Setting, check_value, config_paths, load_config


def _dest(setting: Setting) -> str:
    """argparse attribute name of a flag (--length-tol -> length_tol)."""
    return setting.flag.lstrip("-").replace("-", "_")


def parse_args(argv: list[str], config: Optional[dict] = None) -> argparse.Namespace:
    """The command line on top of the config. The result carries every setting under its
    config key plus `sources` (key -> 'cli' | 'config' | 'default'). Bad values exit with 2."""
    p = argparse.ArgumentParser(
        description="Batch-download playlists via sockseek: one process per playlist, flat output.")
    p.add_argument("--version", action="version", version=f"sockseek-cli {__version__}")
    p.add_argument("--playlists", type=Path, help="folder with playlist .txt files (config: paths.playlists)")
    p.add_argument("--output", type=Path, help="export folder (config: paths.output)")
    p.add_argument("--sockseek", type=Path, help="path to sockseek.exe (config: paths.sockseek)")
    p.add_argument("--only", help="process only this playlist (file name without .txt)")
    p.add_argument("--ffprobe", type=Path,
                   help="ffprobe.exe for --ffprobe-check (default: ffprobe on PATH, then "
                        "C:\\ffmpeg\\bin\\ffprobe.exe)")
    for s in SETTINGS:
        metavar = "MIN" if s.key.endswith("_min") else "SEC" if s.key.endswith("_s") else "N"
        p.add_argument(s.flag, type=s.kind, default=None, metavar=metavar, help=s.help)
    p.add_argument("--dry-run", action="store_true",
                   help="write the list file, print the sockseek command, run nothing")
    p.add_argument("--preview", action="store_true", help="print search results instead of downloading")
    p.add_argument("--ffprobe-check", action="store_true",
                   help="measure every downloaded file with ffprobe and report length/bitrate "
                        "mismatches in the log (off by default, changes nothing on disk)")
    p.add_argument("--no-explain", action="store_true",
                   help="skip the extra search that explains every failed track; it costs one "
                        "query per failure")
    p.add_argument("--verbose", action="store_true",
                   help="sockseek --verbose plus --log-file logs/sockseek_<run number>_<name>.log")
    p.add_argument("--config", type=Path, help=f"settings file (default ./{settings.CONFIG_NAME})")
    p.add_argument("--sockseek-conf", type=Path,
                   help=f"one more {settings.SOCKSEEK_CONF} layer, same syntax, as few keys as "
                        f"you like; it overrides {settings.SOCKSEEK_CONF} and "
                        f"{settings.SOCKSEEK_LOCAL_CONF}")
    p.add_argument("--sockseek-args", default="",
                   help="extra sockseek arguments as one quoted string (shlex-split), e.g. "
                        "--sockseek-args=\"--desperate --artist-maybe-wrong\"")
    args = p.parse_args(argv)

    values = config or {}
    sources: dict[str, str] = {}
    for s in SETTINGS:
        cli_value = getattr(args, _dest(s), None)
        if cli_value is not None:
            value, source = cli_value, "cli"
        elif s.key in values:
            value, source = values[s.key], "config"
        else:
            value, source = s.default, "default"
        problem = check_value(s, value)
        if problem:
            p.error(f"{problem} (source: {source})")
        setattr(args, s.key, value)
        sources[s.key] = source
    folders = config_paths(values, settings.APP_DIR)
    for attr in PATH_KEYS:
        if getattr(args, attr) is not None:
            sources[attr] = "cli"
        else:
            setattr(args, attr, folders[attr])
            sources[attr] = "config" if values.get(attr) else "default"
    if args.config is None:
        args.config, sources["config"] = settings.APP_DIR / settings.CONFIG_NAME, "default"
    else:
        sources["config"] = "cli"
    sources["ffprobe"] = "cli" if args.ffprobe is not None else "default"
    args.sources = sources
    try:
        # posix=False keeps Windows backslashes intact; strip the quotes it leaves on tokens
        args.sockseek_arg_list = tuple(t.strip("\"'")
                                       for t in shlex.split(args.sockseek_args, posix=False))
    except ValueError as exc:
        p.error(f"--sockseek-args: {exc}")
    return args


def describe_config(args: argparse.Namespace) -> list[str]:
    """Effective configuration, one key per line: name = value [source]."""
    lines = [f"effective configuration of sockseek-cli {__version__} "
             f"(key = value [source: cli | config | default]):"]
    for attr, key in (("playlists", "playlists_dir"), ("output", "output_dir"),
                      ("sockseek", "sockseek_exe"), ("config", "config_file"),
                      ("ffprobe", "ffprobe_path")):
        lines.append(f"  {key} = {getattr(args, attr) or 'auto'} [{args.sources[attr]}]")
    for s in SETTINGS:
        value = getattr(args, s.key)
        shown = f"{value:g}" if isinstance(value, float) else value
        lines.append(f"  {s.key} = {shown} [{args.sources[s.key]}]")
    extra = [("only", args.only), ("dry_run", args.dry_run or None),
             ("preview", args.preview or None), ("verbose", args.verbose or None),
             ("explain", False if args.no_explain else None),
             ("ffprobe_check", True if args.ffprobe_check else None),
             ("sockseek_conf", args.sockseek_conf),
             ("sockseek_args", args.sockseek_args or None)]
    for key, value in extra:
        if value is not None:
            lines.append(f"  {key} = {value} [cli]")
    return lines


def options_from_args(args: argparse.Namespace) -> Options:
    return Options(length_tol=args.length_tol_s, preview=args.preview)


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    pre = argparse.ArgumentParser(add_help=False)  # --config must be known first
    pre.add_argument("--config", type=Path, default=settings.APP_DIR / settings.CONFIG_NAME)
    config_path = pre.parse_known_args(argv)[0].config
    messages: list[str] = []
    args = parse_args(argv, load_config(config_path, warn=messages.append))
    return run_batch(
        settings.APP_DIR, args.playlists, args.output, args.sockseek, options_from_args(args),
        timeout_min=args.playlist_timeout_min, retries=args.retries, dry_run=args.dry_run,
        only=args.only, verbose=args.verbose, explain=not args.no_explain,
        ffprobe_check=args.ffprobe_check, sockseek_conf=args.sockseek_conf,
        sockseek_args=args.sockseek_arg_list,
        config_report=tuple(describe_config(args)), early_messages=tuple(messages),
        ffprobe=args.ffprobe,
    )


if __name__ == "__main__":
    sys.exit(main())
