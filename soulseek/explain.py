"""Why a track did not arrive.

After a run, the tracks still missing are searched once more with every condition off. That
costs one search per failure and it is the difference between "nobody shares this" and "our
own conditions rejected it" - a distinction the raw log hides: `reason=9` reads as "no search
results" while it really means "nothing passed the conditions".
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Optional

from .playlist import Entry
from .runner import Sockseek
from .settings import SOCKSEEK_CONF

EXPLAIN_TIMEOUT_S = 600

_RESULT_HEAD_RE = re.compile(r"^Results for (?P<title>.+) \((?P<want>\d+)s\):\s*$")
_RESULT_ROW_RE = re.compile(
    r"^\[(?P<length>\d+)s/(?P<bitrate>[\d?]+)kbps\s*/(?P<size>[\d.?]+)MB\]\s*(?P<path>.+)$")


@dataclass(frozen=True)
class Candidate:
    length: Optional[int]
    bitrate: Optional[int]
    path: str


def parse_preview(text: str) -> dict[str, list[Candidate]]:
    """Group `--print results` output by the title it was searched for. A title with no
    candidates maps to an empty list, which is the whole point."""
    found: dict[str, list[Candidate]] = {}
    current: Optional[str] = None
    for line in text.splitlines():
        head = _RESULT_HEAD_RE.match(line.strip())
        if head:
            current = head.group("title").strip()
            found.setdefault(current, [])
            continue
        if current is None:
            continue
        row = _RESULT_ROW_RE.match(line.strip())
        if row:
            bitrate = int(row.group("bitrate")) if row.group("bitrate").isdigit() else None
            found[current].append(
                Candidate(int(row.group("length")), bitrate, row.group("path").strip()))
    return found


def explain_failure(failure: dict, candidates: Optional[list[Candidate]],
                    length_tol: int, min_bitrate: Optional[int]) -> list[str]:
    """Why this track did not arrive, and what to do about it, as indented log lines."""
    want = None
    try:
        want = int((failure.get("index_length") or "").strip())
    except ValueError:
        pass
    if candidates is None:
        return ["  -> not checked (the explain search did not run for this line)"]
    if not candidates:
        # reason 4 means the main run found candidates and tried to download one, so "nothing on
        # the network" would contradict the index. Measured twice on 2026-10-11 (runs #0028 and
        # #0029): a search fired seconds after the run can come back empty within its 5 s
        # timeout while the same title had hundreds of candidates a moment earlier.
        if (failure.get("failurereason") or "").strip() == "4":
            return ["  -> the extra search came back empty, but the run itself had found a "
                    "candidate: this is a search that did not answer in time, not an absence"]
        return ["  -> nothing on the network: 0 candidates even with every condition off"]

    def gap(c: Candidate) -> int:
        return abs(c.length - want) if c.length is not None and want is not None else 0

    best = min(candidates, key=lambda c: (gap(c), -(c.bitrate or 0)))
    br = f"{best.bitrate}kbps" if best.bitrate is not None else "bitrate unknown"
    lines = [f"  -> IS on the network: {len(candidates)} candidate(s), closest {best.length}s/{br}"]
    if want is not None and best.length is not None and length_tol >= 0 and gap(best) > length_tol:
        lines.append(f"     rejected by length: playlist says {want}s, diff {best.length - want:+d}s")
        lines.append(f"     to take it: py run.py --only <playlist> --length-tol {gap(best) + 1}")
        return lines
    within = [c for c in candidates
              if length_tol < 0 or want is None or c.length is None or gap(c) <= length_tol]
    if min_bitrate is not None and within and all(
            c.bitrate is not None and c.bitrate < min_bitrate for c in within):
        worst = max((c.bitrate or 0) for c in within)
        lines.append(f"     rejected by quality: best is {worst}kbps, below min-bitrate "
                     f"{min_bitrate} in {SOCKSEEK_CONF}")
        return lines
    lines.append("     length and quality are fine, so the uploader did not deliver "
                 "- try again later, availability changes with who is online")
    return lines


def explain_failures(failures: list[dict], entries: list[Entry], list_file: Path,
                     sockseek: Sockseek, out_dir: Path,
                     log: Callable[[str], None]) -> dict[str, list[Candidate]]:
    """One extra sockseek run over the failed tracks with no conditions at all. Downloads
    nothing. Returns the parsed candidates, empty when the step could not run."""
    lines = {f["playlist_line"] for f in failures if f["playlist_line"]}
    wanted = [e for e in entries if e.original in lines]
    if not wanted:
        return {}
    log(f"explaining {len(wanted)} failure(s): {len(wanted)} extra search(es), nothing is downloaded")
    probe = list_file.with_name(list_file.name.replace(".list.txt", ".explain.list.txt"))
    probe.write_text("\n".join(e.list_line for e in wanted) + "\n", encoding="utf-8")
    opts = replace(sockseek.opts, length_tol=-1, preview=True)
    cmd = sockseek.command(probe, out_dir, None, opts)
    try:
        done = subprocess.run(cmd, cwd=sockseek.cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=EXPLAIN_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"WARN explain step did not run: {exc}")
        return {}
    return parse_preview((done.stdout or "") + (done.stderr or ""))
