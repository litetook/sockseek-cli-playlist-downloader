"""Optional ffprobe report on what was downloaded: `--ffprobe-check`.

Off by default (owner, 2026-10-07: the contents of a file are not checked unless asked for).
It only reports - nothing is moved, renamed or deleted, and the exit code never changes.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .index import INDEX_OK, match_index
from .playlist import Entry

FFPROBE_FALLBACK = Path(r"C:\ffmpeg\bin\ffprobe.exe")
FFPROBE_TIMEOUT_S = 30


def find_ffprobe(configured: Optional[Path] = None) -> Optional[Path]:
    """The configured ffprobe if it exists, else ffprobe on PATH, else the fallback path.
    An explicit setting that does not exist is not silently replaced by auto-detection."""
    if configured:
        if configured.is_file():
            return configured
        found = shutil.which(str(configured))
        return Path(found) if found else None
    found = shutil.which("ffprobe")
    if found:
        return Path(found)
    return FFPROBE_FALLBACK if FFPROBE_FALLBACK.is_file() else None


def probe_file(ffprobe: Path, file: Path) -> tuple[Optional[int], Optional[int]]:
    """(duration in whole seconds, bitrate in kbps); None for whatever cannot be read."""
    cmd = [str(ffprobe), "-v", "error", "-show_entries", "format=duration,bit_rate",
           "-of", "csv=p=0", str(file)]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=FFPROBE_TIMEOUT_S,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    fields = (done.stdout or "").strip().split(",")
    duration: Optional[int] = None
    bitrate: Optional[int] = None
    try:
        duration = int(float(fields[0]) + 0.5)
    except (ValueError, IndexError, OverflowError):
        pass
    try:
        bitrate = int(float(fields[1]) / 1000 + 0.5)
    except (ValueError, IndexError, OverflowError):
        pass
    return duration, bitrate


def check_downloads(entries: list[Entry], rows: list[dict], dirs: list[Path], ffprobe: Path,
                    length_tol_s: int, log: Callable[[str], None],
                    min_bitrate: Optional[int] = None) -> list[str]:
    """Measure every downloaded file in the index, one CHECK line each plus a summary.
    Returns the names of the flagged files.

    The `length` column of the index is the length from the playlist line, not a measurement,
    so the entry's own length is what the real duration is compared with. A file below
    min_bitrate is marked LOWQ: sockseek cannot reject those, because it accepts any file whose
    uploader reported no bitrate at all - that is how a 65 kbps opus arrived in run #0002.
    """
    mapping = match_index(entries, rows)
    measured = 0
    flagged: list[str] = []
    low_quality: list[str] = []
    for r, row in enumerate(rows):
        relative = (row.get("filepath") or "").strip()
        if (row.get("state") or "").strip() not in INDEX_OK or not relative:
            continue
        file = dirs[r] / relative
        if not file.is_file():
            continue
        duration, bitrate = probe_file(ffprobe, file)
        measured += 1
        e = mapping.get(r)
        want = entries[e].track.length if e is not None else None
        bad = (want is not None and duration is not None and length_tol_s >= 0
               and abs(duration - want) > length_tol_s)
        low = min_bitrate is not None and bitrate is not None and bitrate < min_bitrate
        want_s = str(want) if want is not None else "?"
        real_s = str(duration) if duration is not None else "?"
        diff_s = f"{duration - want:+d}" if want is not None and duration is not None else "?"
        br_s = f"{bitrate}kbps" if bitrate is not None else "?"
        marks = ("MISMATCH  " if bad else "") + ("LOWQ  " if low else "")
        log(f"CHECK  want={want_s} real={real_s} diff={diff_s:<3} br={br_s}  " + marks + file.name)
        if bad:
            flagged.append(file.name)
        if low:
            low_quality.append(f"{file.name} ({bitrate}kbps)")
    if low_quality:
        log(f"CHECK {len(low_quality)} file(s) below min-bitrate {min_bitrate} "
            f"(the uploader did not report a bitrate, so sockseek could not reject them): "
            + ", ".join(low_quality))
    if not measured:
        return flagged
    if length_tol_s < 0:
        log(f"CHECK 0 of {measured} file(s) flagged, length check is off (length tolerance -1)")
    elif flagged:
        log(f"CHECK {len(flagged)} of {measured} file(s) outside +-{length_tol_s} s: "
            + ", ".join(flagged))
    else:
        log(f"CHECK 0 of {measured} file(s) outside +-{length_tol_s} s")
    return flagged
