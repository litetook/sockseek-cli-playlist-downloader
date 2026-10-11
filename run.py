"""The one command of this tool.

    py run.py

Shows every playlist with how much of it is already on disk, asks which one to work on, shows
exactly which tracks are missing, and downloads only those after an explicit yes. Re-running
the same playlist later is the normal workflow: what arrives depends on who is online right
now (proven 2026-10-07: a track absent on the 6th arrived on the 7th as flac 893 kbps).

Options of this front end:
    --only <name>     skip the menu and take that playlist (file stem, no .txt)
    --yes             skip the confirmation (for a scheduled run)
    --import <file>   turn an exported list (m3u/m3u8/csv/tsv/txt) into a playlist and exit
    --as <name>       name for the imported playlist (default: the file's own name)
    --overwrite       let --import replace a playlist that already exists
    --version         print the version and exit
Anything else is passed straight through to the engine, e.g. --length-tol 60, --verbose,
--ffprobe-check, --no-explain, --dry-run.

A tool it needs but cannot find (sockseek, and later yt-dlp) is offered for download at the
version pinned in dependencies.yaml, so it makes no difference whether setup.py was run first.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import soulseek

APP_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Info:
    """One playlist as the menu shows it."""
    name: str
    path: Path
    total: int
    status: soulseek.Status
    warnings: tuple[str, ...] = ()

    @property
    def missing(self) -> list[soulseek.Entry]:
        return self.status.missing

    @property
    def have(self) -> int:
        return len(self.status.have)


def scan(playlists_dir: Path, output_dir: Path) -> list[Info]:
    """Every playlist in the folder, with what is already downloaded."""
    try:
        files = soulseek.Playlist.find(playlists_dir)
    except OSError:
        return []
    found: list[Info] = []
    for file in files:
        try:
            playlist = soulseek.Playlist.from_file(file)
        except OSError as exc:
            found.append(Info(file.stem, file, 0, soulseek.Status([], [], {}),
                              (f"cannot read: {exc}",)))
            continue
        status = soulseek.playlist_status(playlist.entries, output_dir / file.stem)
        found.append(Info(file.stem, file, len(playlist.entries), status,
                          tuple(playlist.warnings)))
    return found


def format_table(infos: list[Info]) -> list[str]:
    """The menu: number, name, how many tracks, how many are here, how many are missing."""
    width = max([len(i.name) for i in infos] + [8])
    lines = [f"  #  {'playlist'.ljust(width)}  tracks  here  missing",
             f"  -  {'-' * width}  ------  ----  -------"]
    for n, info in enumerate(infos, 1):
        lines.append(f"{n:>3}  {info.name.ljust(width)}  {info.total:>6}  {info.have:>4}  "
                     f"{len(info.missing):>7}")
    return lines


def parse_choice(text: str, count: int) -> Optional[list[int]]:
    """"1" -> [0]; "1,3" -> [0, 2]; "all" -> everything; "" -> []. None means "not understood".

    Numbers are 1-based for the person and 0-based in the result. Duplicates collapse, order is
    kept, and anything out of range makes the whole answer invalid - no silent guessing.
    """
    text = text.strip().lower()
    if not text:
        return []
    if text in ("all", "*"):
        return list(range(count))
    picked: list[int] = []
    for part in text.replace(" ", ",").split(","):
        if not part:
            continue
        if not part.isdigit():
            return None
        number = int(part)
        if not 1 <= number <= count:
            return None
        if number - 1 not in picked:
            picked.append(number - 1)
    return picked


def format_missing(info: Info) -> list[str]:
    """The git-status-like list: what this playlist is still missing, by playlist line."""
    lines = [f"{info.name}: {info.total} tracks, {info.have} here, {len(info.missing)} missing"]
    if info.missing:
        lines.append("")
        lines.append("Missing:")
        for n, entry in enumerate(info.missing, 1):
            lines.append(f"{n:>4}  {entry.original}")
    return lines


def _confirm(ask: Callable[[str], str], count: int) -> bool:
    """[y] download / [n] skip. Anything else asks again; EOF or Ctrl+C means no."""
    while True:
        try:
            answer = ask(f"Download these {count}? [y] yes  [n] no: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no", ""):
            return False


def _import(source: Path, playlists_dir: Path, name: Optional[str], overwrite: bool,
            out: Callable[[str], None]) -> int:
    """--import: write a playlist from an exported list and report what happened."""
    if not source.is_file():
        out(f"No such file: {source}")
        return 2
    written, found = soulseek.import_file(source, playlists_dir, name, overwrite)
    for warning in found.warnings:
        out(f"WARN {warning}")
    if written is None:
        out(f"Nothing imported from {source.name} (recognised as: {found.source}).")
        if found.lines:
            out("Pass --overwrite to replace the existing playlist.")
        return 2
    with_length = sum(1 for line in found.lines if "|" in line)
    out(f"{written.name}: {len(found.lines)} track(s) from {source.name} "
        f"(format: {found.source}), {with_length} with a length.")
    out(f"Now run: py run.py --only {written.stem}")
    return 0


def _have_sockseek(config: dict, ask: Optional[Callable[[str], str]],
                   out: Callable[[str], None]) -> bool:
    """Make sure sockseek is there before the first download is promised.

    A configured path that exists is left alone; only a missing binary triggers the offer to
    fetch the pinned version (dependencies.yaml) into the tool's own folder.
    """
    configured = soulseek.config_paths(config, APP_DIR)["sockseek"]
    if configured.is_file():
        return True

    def confirm(question: str) -> bool:
        if ask is None:
            return True  # --yes: a scheduled run must not stop on a question
        try:
            return ask(f"{question} [y] yes  [n] no: ").strip().lower() in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    out(f"sockseek is not at {configured}")
    found = soulseek.ensure_tool("sockseek", out, config=soulseek.deps.load(),
                                 app_dir=APP_DIR, ask=confirm)
    if found is None:
        out("Without sockseek nothing can be downloaded. See the README, or run: py setup.py")
        return False
    return True


def main(argv: Optional[list[str]] = None,
         ask: Callable[[str], str] = input,
         out: Callable[[str], None] = print,
         engine: Callable[[list[str]], int] = soulseek.main) -> int:
    """Pick, show, confirm, download. Returns the worst exit code of the runs it started."""
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--only")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--import", dest="import_file", type=Path)
    parser.add_argument("--as", dest="import_name")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    args, extra = parser.parse_known_args(argv)
    if args.help:
        out(__doc__.strip())
        return 0
    if args.version:
        out(f"sockseek-cli {soulseek.__version__}")
        return 0

    config = soulseek.load_config(APP_DIR / soulseek.CONFIG_NAME, warn=out)
    folders = soulseek.config_paths(config, APP_DIR)
    playlists_dir, output_dir = folders["playlists"], folders["output"]

    if args.import_file is not None:
        return _import(args.import_file, playlists_dir, args.import_name, args.overwrite, out)

    infos = scan(playlists_dir, output_dir)
    if not infos:
        out(f"No playlist .txt files in {playlists_dir}")
        return 2

    if args.only:
        chosen = [i for i in infos if i.name == args.only]
        if not chosen:
            out(f"No playlist named '{args.only}' in {playlists_dir}")
            return 2
    else:
        out("Playlists:")
        out("")
        for line in format_table(infos):
            out(line)
        out("")
        while True:
            try:
                answer = ask("What to download? (1, or 1,2, or all; Enter quits): ")
            except (EOFError, KeyboardInterrupt):
                return 0
            picked = parse_choice(answer, len(infos))
            if picked is None:
                out(f"Type a number from 1 to {len(infos)}, several separated by commas, or all.")
                continue
            if not picked:
                return 0
            chosen = [infos[n] for n in picked]
            break

    if not _have_sockseek(config, ask if not args.yes else None, out):
        return 2
    worst = 0
    for info in chosen:
        out("")
        for line in format_missing(info):
            out(line)
        for warning in info.warnings:
            out(f"WARN {warning}")
        if not info.missing:
            out("Nothing to do.")
            continue
        out("")
        if not args.yes and not _confirm(ask, len(info.missing)):
            out("Skipped.")
            continue
        out("")
        worst = max(worst, engine(["--only", info.name] + extra))
    return worst


if __name__ == "__main__":
    sys.exit(main())
