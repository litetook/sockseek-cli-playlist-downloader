"""Turning an exported track list into a playlist file.

The playlist `.txt` stays the tool's own interface: it is readable, editable by hand, diffable
and needs no network. This module only fills it in from what another program exported, so the
fragile part (someone else's format) cannot break the engine.

Supported now: `.m3u` / `.m3u8` (EXTINF), `.csv` / `.tsv` with a header, and a plain text list.
A link to Spotify or SoundCloud is a separate input interface and is not here yet.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .playlist import parse_duration, read_playlist

TITLE_COLUMNS = ("track name", "title", "name", "track", "song", "track title")
ARTIST_COLUMNS = ("artist name(s)", "artist", "artists", "artist name", "album artist")
LENGTH_COLUMNS = ("duration (ms)", "duration_ms", "duration", "time", "length", "track duration")

EXTINF = "#EXTINF:"
NEWLINE = chr(10)


IMPLAUSIBLE_SECONDS = 4 * 3600  # a single track four hours long: the number must be millis


def _seconds(text: str, column: str = "", guess_ms: bool = False) -> Optional[int]:
    """A duration out of an exported cell: m:ss, seconds, or milliseconds.

    Milliseconds are recognised by the column name ("Duration (ms)" in a Spotify export) and,
    when `guess_ms` is set, by a value too large to be seconds. m3u passes guess_ms=False
    because #EXTINF is defined in seconds - a 64-minute set is 3875 there, not 3.9 seconds.
    """
    text = (text or "").strip()
    if not text:
        return None
    if ":" in text:
        return parse_duration(text)
    try:
        number = float(text)
    except ValueError:
        return None
    if number <= 0:
        return None
    if "ms" in column.lower() or (guess_ms and number > IMPLAUSIBLE_SECONDS):
        return int(number / 1000 + 0.5)
    return int(number + 0.5)


def track_line(name: str, length: Optional[int]) -> str:
    """One playlist line: `Name | m:ss`, or just the name when the length is unknown."""
    name = " ".join(name.split())
    if length is None:
        return name
    return f"{name} | {length // 60}:{length % 60:02d}"


@dataclass(frozen=True)
class Imported:
    """What one import produced."""
    lines: list[str]
    warnings: list[str]
    source: str  # the format that was recognised

    def text(self) -> str:
        return "\n".join(self.lines) + "\n" if self.lines else ""


class Importer:
    """Reads an exported list and gives back playlist lines."""

    def read(self, path: Path) -> Imported:
        text, note = read_playlist(path)
        warnings = [note] if note else []
        suffix = path.suffix.lower()
        if suffix in (".m3u", ".m3u8") or text.lstrip().startswith("#EXTM3U"):
            found = self.from_m3u(text)
        elif suffix in (".csv", ".tsv") or self._looks_tabular(text):
            found = self.from_table(text)
        else:
            found = self.from_text(text)
        return Imported(found.lines, warnings + found.warnings, found.source)

    @staticmethod
    def _looks_tabular(text: str) -> bool:
        head = text.splitlines()[0].lower() if text.strip() else ""
        return any(name in head for name in TITLE_COLUMNS) and ("," in head or "\t" in head)

    def from_m3u(self, text: str) -> Imported:
        """`#EXTINF:249,Artist - Title` pairs; the file path lines are ignored."""
        lines: list[str] = []
        warnings: list[str] = []
        for raw in text.splitlines():
            raw = raw.strip()
            if not raw.startswith(EXTINF):
                continue
            body = raw[len(EXTINF):]
            seconds, _, name = body.partition(",")
            name = name.strip()
            if not name:
                warnings.append(f"skipped an entry without a title: {raw!r}")
                continue
            length = _seconds(seconds)
            lines.append(track_line(name, length if length and length > 0 else None))
        if not lines:
            warnings.append("no #EXTINF entries found - is this really an m3u playlist?")
        return Imported(lines, warnings, "m3u")

    def from_table(self, text: str) -> Imported:
        """A csv/tsv export with a header: title, artist and duration columns are looked up
        by name (see TITLE_COLUMNS and friends), everything else is ignored."""
        delimiter = "\t" if text.splitlines()[0].count("\t") else ","
        rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
        if not rows:
            return Imported([], ["the table has a header but no rows"], "table")
        header = {(name or "").strip().lower(): name for name in rows[0]}
        title_col = self._column(header, TITLE_COLUMNS)
        artist_col = self._column(header, ARTIST_COLUMNS)
        length_col = self._column(header, LENGTH_COLUMNS)
        if title_col is None:
            return Imported([], [f"no title column: looked for {', '.join(TITLE_COLUMNS)}; "
                                 f"the header has {', '.join(sorted(header))}"], "table")
        lines: list[str] = []
        warnings: list[str] = []
        if length_col is None:
            warnings.append("no duration column, the lines will have no length - the length is "
                            "what keeps another version of the song out")
        for number, row in enumerate(rows, start=2):
            title = (row.get(title_col) or "").strip()
            if not title:
                warnings.append(f"row {number}: skipped (no title)")
                continue
            artist = (row.get(artist_col) or "").strip() if artist_col else ""
            length = (_seconds(row.get(length_col) or "", length_col or "", guess_ms=True)
                      if length_col else None)
            name = f"{artist} - {title}" if artist else title
            lines.append(track_line(name, length))
        return Imported(lines, warnings, "table")

    def from_text(self, text: str) -> Imported:
        """A plain list of names, one per line. Lines that already carry `| 4:09` are kept
        as they are, so re-importing a playlist of ours changes nothing."""
        lines: list[str] = []
        for raw in text.splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            lines.append(" ".join(raw.split()))
        warnings = [] if lines else ["the file has no usable lines"]
        return Imported(lines, warnings, "text")

    @staticmethod
    def _column(header: dict[str, str], names: tuple[str, ...]) -> Optional[str]:
        for name in names:
            if name in header:
                return header[name]
        for key, original in header.items():  # "artist(s)" and the like
            if any(name in key for name in names):
                return original
        return None


def import_file(source: Path, playlists_dir: Path, name: Optional[str] = None,
                overwrite: bool = False) -> tuple[Optional[Path], Imported]:
    """Write `<playlists_dir>/<name>.txt` from an exported list.

    Returns (written path or None, what was read). Nothing is written when the import found no
    lines, or when the playlist exists and overwrite is False - a playlist is hand-edited, so
    silently replacing it would throw that work away.
    """
    found = Importer().read(source)
    if not found.lines:
        return None, found
    written, refused = write_playlist(found.lines, playlists_dir, name or source.stem,
                                      overwrite)
    if written is None:
        return None, Imported(found.lines, found.warnings + [refused or ""], found.source)
    return written, found


def write_playlist(lines: list[str], playlists_dir: Path, name: str,
                   overwrite: bool = False) -> tuple[Optional[Path], Optional[str]]:
    """Write `<playlists_dir>/<name>.txt`. Returns (path, None), or (None, why not).

    A playlist is hand-edited, so an existing one is never replaced without --overwrite.
    """
    target = playlists_dir / f"{(name or 'playlist').strip()}.txt"
    if target.exists() and not overwrite:
        return None, f"{target.name} already exists"
    playlists_dir.mkdir(parents=True, exist_ok=True)
    text = NEWLINE.join(lines) + NEWLINE if lines else ""
    target.write_text(text, encoding="utf-8", newline=NEWLINE)
    return target, None
