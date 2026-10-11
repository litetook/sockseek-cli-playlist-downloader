"""sockseek's `_index.csv`: the only link between a playlist line and a file on disk.

File names come from the uploader (`... (Clean) 1A 142 [www.dj-promo.org].mp3`), so a line
cannot be recovered from a name. The index can, which is why "already here" is decided here.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .playlist import Entry

INDEX_NAME = "_index.csv"

# state column, verified with --mock-files-dir on 2026-10-07: 1 = downloaded now,
# 3 = already present and skipped (sockseek calls it "succeeded"), 2 = failed.
# Without 3 every re-run would report everything downloaded earlier as failed.
INDEX_OK = frozenset({"1", "3"})

# failurereason, read off real logs on 2026-10-07. 9 does NOT mean "not on the network":
# run #0004 found two 320 kbps files for a track whose row said 9.
REASON_TEXT = {
    "9": "no candidate passed the name/length/quality conditions",
    "4": "found, but the download did not come through",
}


def find_index_files(out_dir: Path) -> list[Path]:
    """<out_dir>/_index.csv. The glob is a fallback for indexes left by older versions."""
    direct = out_dir / INDEX_NAME
    if direct.is_file():
        return [direct]
    try:
        return sorted(p for p in out_dir.glob(f"**/{INDEX_NAME}") if p.is_file())
    except OSError:
        return []


def read_index_with_dirs(paths: list[Path]) -> tuple[list[dict], list[Path]]:
    """Rows of the given index files, plus the folder each row came from: its `filepath`
    is relative to that folder."""
    rows: list[dict] = []
    dirs: list[Path] = []
    for path in paths:
        try:
            with path.open(encoding="utf-8-sig", newline="") as fh:
                part = list(csv.DictReader(fh))
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
        rows.extend(part)
        dirs.extend([path.parent] * len(part))
    return rows, dirs


def read_index(paths: list[Path]) -> list[dict]:
    return read_index_with_dirs(paths)[0]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def match_index(entries: list[Entry], rows: list[dict]) -> dict[int, Optional[int]]:
    """Index row number -> entry number. Matched by title text, with the artist column put
    back in front of it (that is the shape a search with --extract-artist leaves). A row that
    matches nothing is paired by position only when the counts are equal: no guessing."""
    mapping: dict[int, Optional[int]] = {}
    taken: set[int] = set()
    for r, row in enumerate(rows):
        title, artist = _norm(row.get("title", "")), _norm(row.get("artist", ""))
        candidates = {title, f"{artist} - {title}" if artist else title}
        mapping[r] = None
        for e, entry in enumerate(entries):
            if e in taken:
                continue
            track = entry.track
            keys = {_norm(track.title),
                    _norm(f"{track.artist} - {track.title}") if track.artist else _norm(track.title)}
            if keys & candidates:
                mapping[r] = e
                taken.add(e)
                break
    if len(rows) == len(entries):
        for r in range(len(rows)):
            if mapping[r] is None and r not in taken:
                mapping[r] = r
                taken.add(r)
    return mapping


@dataclass(frozen=True)
class Status:
    """What of a playlist is already on disk and what is still missing."""
    have: list[Entry]
    missing: list[Entry]
    files: dict[str, Path]  # playlist line -> the file it already has


def playlist_status(entries: list[Entry], out_dir: Path) -> Status:
    """Which lines already have a file, and which do not.

    A row counts only when BOTH hold: its state says arrived and the file is really on disk.
    A row whose file was deleted reads as missing again, and no index at all means everything
    is missing - exactly right for a first run.
    """
    rows, dirs = read_index_with_dirs(find_index_files(out_dir))
    mapping = match_index(entries, rows)
    files: dict[str, Path] = {}
    for r, row in enumerate(rows):
        e = mapping.get(r)
        if e is None or (row.get("state") or "").strip() not in INDEX_OK:
            continue
        relative = (row.get("filepath") or "").strip()
        if not relative:
            continue
        path = dirs[r] / relative
        if path.is_file():
            files.setdefault(entries[e].original, path)
    return Status(have=[e for e in entries if e.original in files],
                  missing=[e for e in entries if e.original not in files],
                  files=files)


def rows_by_entry(entries: list[Entry], rows: list[dict]) -> dict[str, dict]:
    """Playlist line -> its index row, to read the state and the reason code off it."""
    mapping = match_index(entries, rows)
    found: dict[str, dict] = {}
    for r, row in enumerate(rows):
        e = mapping.get(r)
        if e is not None:
            found.setdefault(entries[e].original, row)
    return found


def failure_dict(line: str, row: Optional[dict]) -> dict:
    """The shape the report and the explain step expect for one failed track."""
    row = row or {}
    return {"playlist_line": line,
            "index_title": row.get("title", ""),
            "index_length": row.get("length", ""),
            "state": row.get("state", ""),
            "failurereason": row.get("failurereason", "")}


def failure_rows(entries: list[Entry], rows: list[dict]) -> list[dict]:
    """Every index row whose state is not OK, as failure dicts. An empty playlist_line means
    the row matches no line in this playlist."""
    mapping = match_index(entries, rows)
    result: list[dict] = []
    for r, row in enumerate(rows):
        if (row.get("state") or "").strip() in INDEX_OK:
            continue
        e = mapping.get(r)
        result.append(failure_dict(entries[e].original if e is not None else "", row))
    return result


def format_failure(failure: dict) -> str:
    """One log line for a failed track."""
    reason = (failure["failurereason"] or "?").strip()
    meaning = REASON_TEXT.get(reason, "unknown reason code")
    head = f"FAILED  state={failure['state'] or '?'} reason={reason} ({meaning})  "
    if failure["playlist_line"]:
        return head + failure["playlist_line"]
    return head + f"(no matching playlist line, index title: {failure['index_title']})"
