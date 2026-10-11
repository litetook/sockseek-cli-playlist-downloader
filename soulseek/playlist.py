"""Playlist files: one `.txt` per playlist, one track per line.

    Artist - Title | 4:09

The length after `|` is what protects us from downloading another version of the song; a line
without it searches without the length filter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

LINE_RE = re.compile(r"^(?P<name>.+?)\s*\|\s*(?P<length>[\d:.]+)\s*$")


@dataclass(frozen=True)
class Track:
    artist: str
    title: str
    length: Optional[int]  # seconds, None when the line has no length


@dataclass(frozen=True)
class Entry:
    """One playlist line, ready for sockseek."""
    list_line: str
    original: str
    track: Track


def parse_duration(text: str) -> Optional[int]:
    """'4:09' -> 249, '1:04:35' -> 3875, '249' -> 249, '4.9' -> 5 (rounded). None if invalid."""
    parts = text.strip().split(":")
    if not 1 <= len(parts) <= 3:
        return None
    total = 0.0
    try:
        for part in parts:
            if part == "":
                return None
            total = total * 60 + float(part)
        if total < 0:
            return None
        return int(total + 0.5)
    except (ValueError, OverflowError):
        return None


def _clean(text: str) -> str:
    """Commas separate properties in a sockseek search string, quotes break the line."""
    return re.sub(r"\s+", " ", text.replace(",", " ").replace('"', "")).strip()


def parse_line(line: str) -> Optional[Track]:
    """Parse 'Name | 4:09'. Blank lines and '#' comments give None.

    The whole name is searched as one string: a playlist line is a free-form title like
    'Nova Blue - Kate Ryan - Song (Remix)', where splitting artist from title is a guess.
    Proven on 2026-10-07 (runs #0004/#0005): the search finds the same files either way.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    length: Optional[int] = None
    match = LINE_RE.match(line)
    if match:
        length = parse_duration(match.group("length"))
        line = match.group("name").strip()
    title = _clean(line)
    if not title:
        return None
    return Track(artist="", title=title, length=length)


def build_list_line(track: Track) -> str:
    """One sockseek list-file line, e.g. s:"title=T, length=249"."""
    props = []
    if track.artist:
        props.append(f"artist={track.artist}")
    props.append(f"title={track.title}")
    if track.length is not None:
        props.append(f"length={track.length}")
    return 's:"' + ", ".join(props) + '"'


def is_generated(path: Path) -> bool:
    """Files the tool wrote itself are not playlists of their own."""
    return path.name.startswith("tracks_") or path.name.endswith(".list.txt")


def read_playlist(path: Path) -> tuple[str, Optional[str]]:
    """Read a playlist as UTF-8, falling back to cp1251 and then latin-1; never raises on
    encoding. Returns (text, warning or None). The fallback is a guess, not a detection."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1251"), "not valid UTF-8, decoded as cp1251 - check the file"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "not valid UTF-8 or cp1251, decoded as latin-1 - check the file"


def convert_playlist(text: str) -> tuple[list[Entry], list[str]]:
    """(entries, warnings) for one playlist file. Identical lines are dropped."""
    entries: list[Entry] = []
    warnings: list[str] = []
    seen: set[str] = set()
    duplicates = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        track = parse_line(raw)
        if track is None:
            if raw.strip() and not raw.strip().startswith("#"):
                warnings.append(f"line {number}: skipped (no title): {raw.strip()!r}")
            continue
        list_line = build_list_line(track)
        if list_line in seen:
            duplicates += 1
            continue
        seen.add(list_line)
        if track.length is None:
            warnings.append(f"line {number}: no valid length, searching without length filter")
        entries.append(Entry(list_line, raw.strip(), track))
    if duplicates:
        warnings.append(f"{duplicates} duplicate line(s) dropped")
    return entries, warnings


@dataclass(frozen=True)
class Playlist:
    """A playlist file read into entries."""
    name: str
    path: Path
    entries: list[Entry]
    warnings: list[str]

    @classmethod
    def from_file(cls, path: Path) -> "Playlist":
        text, note = read_playlist(path)
        entries, warnings = convert_playlist(text)
        if note:
            warnings = [note, *warnings]
        return cls(name=path.stem, path=path, entries=entries, warnings=warnings)

    @staticmethod
    def find(playlists_dir: Path) -> list[Path]:
        """Every playlist file in the folder, generated ones excluded."""
        return sorted(f for f in playlists_dir.glob("*.txt") if not is_generated(f))

    def __len__(self) -> int:
        return len(self.entries)
