"""The one command of this tool.

    py run.py

Asks where the list comes from - a .txt file you already have, a Spotify link or a
SoundCloud link - then shows every playlist with how much of it is already on disk, asks which
one to work on, shows exactly which tracks are missing, and downloads only those after an
explicit yes. A link is saved as a .txt first, so it joins the same flow. Re-running
the same playlist later is the normal workflow: what arrives depends on who is online right
now (proven 2026-10-07: a track absent on the 6th arrived on the 7th as flac 893 kbps).

Options of this front end:
    --only <name>     skip the menu and take that playlist (file stem, no .txt)
    --yes             skip the confirmation (for a scheduled run)
    --import <what>   turn an exported list (m3u/m3u8/csv/tsv/txt) or a playlist link
                      (Spotify, SoundCloud) into a playlist file and exit
    --as <name>       name for the imported playlist (default: its name at the source)
    --overwrite       let --import replace a playlist that already exists
    --cookies-from-browser <browser>
                      read a private SoundCloud set with the browser's own login
                      (chrome, firefox, edge, brave, ...) - you log in there, not here
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

APP_DIR = soulseek.APP_DIR  # one folder for everything, decided by the engine


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


SERVICE_NAMES = {"spotify": "Spotify", "soundcloud": "SoundCloud"}
SOURCES = (("1", "txt", "download a playlist from a .txt file"),
           ("2", "spotify", "save a .txt from a Spotify link, then download it"),
           ("3", "soundcloud", "save a .txt from a SoundCloud link, then download it"))


def _source_menu(ask: Callable[[str], str], out: Callable[[str], None]) -> Optional[str]:
    """The first question of an interactive run. None means quit.

    A scripted run (--only, --import, --yes) never sees this: it already said where to look.
    """
    out("Where from?")
    out("")
    for key, _, text in SOURCES:
        out(f"  {key}  {text}")
    out("")
    while True:
        try:
            answer = ask("Pick one (Enter quits): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if not answer:
            return None
        for key, name, _ in SOURCES:
            if answer in (key, name):
                return name
        out("Type 1, 2 or 3, or Enter to quit.")


def _ask_for_link(service: str, ask: Callable[[str], str],
                  out: Callable[[str], None]) -> Optional[str]:
    """The link for option 2 or 3. None means the person changed their mind."""
    out("")
    try:
        url = ask(f"Paste the {SERVICE_NAMES.get(service, service)} link "
                  f"(Enter cancels): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return url or None


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
        if not (part.isascii() and part.isdecimal()):
            return None  # "2".isdigit() is true for superscripts too, and int() rejects those
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


def _import_link(url: str, playlists_dir: Path, name: Optional[str], overwrite: bool,
                 out: Callable[[str], None], config: dict, cookies_from: Optional[str],
                 ask: Optional[Callable[[str], str]],
                 reader: Optional[soulseek.LinkReader] = None) -> int:
    """--import <link>: write the playlist file and stop there."""
    code, written = _link_to_playlist(url, playlists_dir, name, overwrite, out, config,
                                      cookies_from, ask, reader)
    if written is not None:
        out(f"Now run: py run.py --only {written.stem}")
    return code


def _link_to_playlist(url: str, playlists_dir: Path, name: Optional[str], overwrite: bool,
                      out: Callable[[str], None], config: dict, cookies_from: Optional[str],
                      ask: Optional[Callable[[str], str]],
                      reader: Optional[soulseek.LinkReader] = None,
                      ask_overwrite: bool = False) -> tuple[int, Optional[Path]]:
    """A Spotify or SoundCloud link -> a playlist file. Returns (exit code, the file).

    Only the track list is taken. The downloading stays with the engine, so a link ends up in
    the same place a hand-written list does: a file you can read, edit and re-run.
    """
    if soulseek.detect(url) is None:
        out(f"Not a link this tool can read: {url}")
        out("Spotify and SoundCloud playlists are supported.")
        return 2, None
    tool = None
    if soulseek.detect(url) == "soundcloud":
        # sockseek has no SoundCloud input type, so this one needs yt-dlp - fetched on demand,
        # and only after the person agreed to the download
        # deps.load() reads dependencies.yaml: `config` here is config.yaml and knows
        # nothing about pinned tools
        tool = soulseek.ensure_tool("yt-dlp", out, config=soulseek.deps.load(), app_dir=APP_DIR,
                                    ask=None if ask is None else
                                    lambda question: _yes(ask, question))
        if tool is None:
            out("Without yt-dlp a SoundCloud link cannot be read. Run: py setup.py --all")
            return 2, None
    out(f"Reading {url}")
    linked = (reader or soulseek.LinkReader()).read(url, tool, cookies_from)
    for warning in linked.warnings:
        out(f"WARN {warning}")
    if not linked.lines:
        out("Nothing imported.")
        return 2, None
    stem = name or soulseek.slug(linked.name) or "playlist"
    target = playlists_dir / f"{stem}.txt"
    if target.is_file() and not overwrite and ask_overwrite and ask is not None:
        # a playlist is hand-edited, so the choice is the person's, not a flag's
        overwrite = _replace(ask, target.name)
        if not overwrite:
            out(f"Keeping {target.name} as it is.")
            return 0, target
    written, refused = soulseek.write_playlist(linked.lines, playlists_dir, stem, overwrite)
    if written is None:
        out(f"Nothing written: {refused}. Pass --overwrite to replace it.")
        return 2, None
    with_length = sum(1 for line in linked.lines if "|" in line)
    out(f"{written.name}: {len(linked.lines)} track(s) from {linked.source}"
        f"{f' ({linked.name})' if linked.name else ''}, {with_length} with a length.")
    return 0, written


def _replace(ask: Callable[[str], str], name: str) -> bool:
    """Replace the existing playlist, or keep it and work on what is already in it."""
    while True:
        try:
            answer = ask(f"{name} already exists. [r] replace  [k] keep it: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if answer in ("r", "replace"):
            return True
        if answer in ("k", "keep", ""):
            return False


def _yes(ask: Callable[[str], str], question: str) -> bool:
    """A yes/no question for the tool downloads, with the same answers as the main one."""
    try:
        return ask(f"{question} [y] yes  [n] no: ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
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
         engine: Callable[[list[str]], int] = soulseek.main,
         reader: Optional[soulseek.LinkReader] = None) -> int:
    """Pick, show, confirm, download. Returns the worst exit code of the runs it started."""
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--only")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--import", dest="import_source")
    parser.add_argument("--cookies-from-browser", dest="cookies_from")
    parser.add_argument("--as", dest="import_name")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    # the three path options are read HERE as well, not merely passed on: the menu and the
    # "here / missing" counts have to look at the folders the engine will actually use
    parser.add_argument("--playlists", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path)
    args, extra = parser.parse_known_args(argv)
    for flag, value in (("--playlists", args.playlists), ("--output", args.output),
                        ("--config", args.config)):
        if value is not None:
            extra += [flag, str(value)]
    if args.help:
        out(__doc__.strip())
        return 0
    if args.version:
        out(f"sockseek-cli {soulseek.__version__}")
        return 0

    created = soulseek.ensure_files(APP_DIR, out)
    if soulseek.SOCKSEEK_LOCAL_CONF in created:
        out("")
        out(f"Put your Soulseek login in {APP_DIR / soulseek.SOCKSEEK_LOCAL_CONF}:")
        out("    username = your-login")
        out("    password = your-password")
        out("Then run this again. Nothing can be downloaded until then.")
        return 2
    config = soulseek.load_config(args.config or APP_DIR / soulseek.CONFIG_NAME, warn=out)
    folders = soulseek.config_paths(config, APP_DIR)
    playlists_dir = args.playlists or folders["playlists"]
    output_dir = args.output or folders["output"]

    if args.import_source is not None:
        if soulseek.is_link(args.import_source):
            return _import_link(args.import_source, playlists_dir, args.import_name,
                                args.overwrite, out, config, args.cookies_from, ask, reader)
        return _import(Path(args.import_source), playlists_dir, args.import_name,
                       args.overwrite, out)

    # the opening question comes before the scan: with an empty Playlists folder, pasting a
    # link is exactly what a new user needs, and "no playlist files" would be a dead end
    source = "txt"
    if ask is not None and not args.only and not args.yes:
        source = _source_menu(ask, out)
        if source is None:
            return 0

    if source != "txt":
        url = _ask_for_link(source, ask, out)
        if url is None:
            return 0
        code, written = _link_to_playlist(url, playlists_dir, args.import_name, args.overwrite,
                                          out, config, args.cookies_from, ask, reader,
                                          ask_overwrite=True)
        if written is None:
            return code
        infos = scan(playlists_dir, output_dir)
        chosen = [i for i in infos if i.name == written.stem]
        if not chosen:
            out(f"Wrote {written.name}, but reading it back found nothing. Look at the file.")
            return 1
    elif args.only:
        infos = scan(playlists_dir, output_dir)
        chosen = [i for i in infos if i.name == args.only]
        if not chosen:
            out(f"No playlist named '{args.only}' in {playlists_dir}")
            return 2
    else:
        infos = scan(playlists_dir, output_dir)
        if not infos:
            out(f"No playlist .txt files in {playlists_dir}")
            return 2
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
        # the tool is asked for only once the answer is yes: nobody wants to be asked about a
        # 50 MB download before seeing what it would be for
        if not _have_sockseek(config, ask if not args.yes else None, out):
            return 2
        out("")
        code = engine(["--only", info.name] + extra)
        worst = max(worst, code)
        if code == 130:  # Ctrl+C means stop the session, not "skip to the next playlist"
            out("Interrupted.")
            break
    return worst


if __name__ == "__main__":
    sys.exit(main())
