"""The run itself: for every chosen playlist, search ONLY what is missing and report.

A re-run of the same playlist is the normal workflow - what arrives depends on who is online
right now - so the tracks already on disk are not searched at all, not even to be skipped.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import quality
from .explain import explain_failure, explain_failures
from .index import (INDEX_NAME, INDEX_OK, failure_dict, find_index_files, format_failure,
                    playlist_status, read_index_with_dirs, rows_by_entry)
from .playlist import Entry, Playlist
from .runner import ERROR, OK, Options, Sockseek, TIMEOUT, run_with_retry
from .settings import (SOCKSEEK_CONF, SOCKSEEK_LOCAL_CONF, effective_conf,
                       missing_credentials, read_min_bitrate)

SEQ_NAME = "run_seq.txt"  # in logs/: the last run number used, a single integer


@dataclass(frozen=True)
class Result:
    """Outcome of one playlist. `broke` is the only thing that makes a run a failure: a track
    nobody shares is news about Soulseek, not an error in this tool."""
    total: int = 0
    missing: int = 0
    broke: bool = False


@dataclass(frozen=True)
class RunConfig:
    app_dir: Path
    playlists_dir: Path
    output_dir: Path
    sockseek: Path
    opts: Options = Options()
    timeout_min: float = 40.0
    retries: int = 2
    dry_run: bool = False
    only: Optional[str] = None
    verbose: bool = False
    explain: bool = True
    ffprobe_check: bool = False
    sockseek_args: tuple[str, ...] = ()
    ffprobe: Optional[Path] = None  # None = auto-detect
    conf: Optional[Path] = None  # the merged sockseek config, written into work/
    sockseek_conf: Optional[Path] = None  # one more layer, from --sockseek-conf
    run_no: int = 0
    stamp: datetime = field(default_factory=datetime.now)
    ffprobe_state: dict = field(default_factory=dict)  # lazy lookup: one "not found" WARN per run

    def client(self) -> Sockseek:
        return Sockseek(exe=self.sockseek, cwd=self.app_dir, opts=self.opts,
                        extra_args=tuple(self.sockseek_args), timeout_min=self.timeout_min,
                        retries=self.retries, conf=self.conf)


def next_run_number(logs_dir: Path) -> tuple[int, list[str]]:
    """The next number from logs/run_seq.txt, written back at once.

    Never raises: a missing or garbled file is rebuilt from the highest run_<digits>_*.log
    with a WARN, and a counter that cannot be written gives number 0 and the run goes on.
    """
    seq = logs_dir / SEQ_NAME
    warnings: list[str] = []
    last: Optional[int] = None
    try:
        raw = seq.read_text(encoding="utf-8-sig").strip()
        if re.fullmatch(r"\d+", raw):
            last = int(raw)
    except (OSError, UnicodeDecodeError):
        pass
    if last is None:
        highest = 0
        try:
            for path in logs_dir.glob("run_*.log"):
                found = re.fullmatch(r"run_(\d+)_.*\.log", path.name)
                if found:
                    highest = max(highest, int(found.group(1)))
        except OSError:
            pass
        last = highest
        warnings.append(f"WARN {SEQ_NAME} is missing or not a number, run counter rebuilt from "
                        f"the log file names in {logs_dir}: highest number found {highest}")
    number = last + 1
    try:
        seq.write_text(f"{number}\n", encoding="utf-8")
    except OSError as exc:
        warnings.append(f"WARN cannot write {seq} ({exc}), using run number 0")
        number = 0
    return number, warnings


def run_label(number: int) -> str:
    """0043 for run 43; numbers past 9999 just get longer."""
    return f"{number:04d}"


class Batch:
    """One invocation: the run number, the log file, and every playlist it was given."""

    def __init__(self, cfg: RunConfig, logs_dir: Path, work_dir: Path, log: Callable[[str], None]):
        self.cfg = cfg
        self.logs_dir = logs_dir
        self.work_dir = work_dir
        self.log = log

    def playlists(self) -> tuple[list[Path], Optional[int]]:
        """The playlist files to process, or (…, exit code) when there is nothing to do."""
        cfg = self.cfg
        try:
            if not cfg.playlists_dir.is_dir():
                cfg.playlists_dir.mkdir(parents=True)
                self.log(f"created {cfg.playlists_dir}, put playlist .txt files there")
                return [], 2
            files = Playlist.find(cfg.playlists_dir)
        except OSError as exc:
            self.log(f"ERROR: cannot read playlists folder: {exc}")
            return [], 2
        if cfg.only:
            named = cfg.playlists_dir / f"{cfg.only}.txt"
            files = [named] if named.is_file() else [f for f in files if f.stem == cfg.only]
            if not files:
                self.log(f"ERROR: no playlist named '{cfg.only}' in {cfg.playlists_dir}")
                return [], 2
        if not files:
            self.log(f"ERROR: no playlist .txt files in {cfg.playlists_dir}")
            return [], 2
        return files, None

    def run(self) -> int:
        files, problem = self.playlists()
        if problem is not None:
            return problem
        results: list[tuple[str, Result]] = []
        broken: list[str] = []
        try:
            for file in files:
                self.log(f"=== {file.stem}")
                try:
                    result = self.one(file)
                except OSError as exc:  # one broken playlist must not stop the others
                    self.log(f"ERROR: {file.stem}: {exc}")
                    result = Result(broke=True)
                results.append((file.stem, result))
                if result.broke:
                    broken.append(file.stem)
        except KeyboardInterrupt:
            self.log("interrupted (Ctrl+C), stopping")
            return 130

        total = sum(r.total for _, r in results)
        missing = sum(r.missing for _, r in results)
        tag = f"run #{run_label(self.cfg.run_no)}"
        if self.cfg.dry_run or self.cfg.opts.preview:
            self.log(f"all done, nothing downloaded ({tag})")
        else:
            self.log(f"{total - missing} of {total} track(s) in the folders, "
                     f"{missing} still missing ({tag})")
        if broken:
            self.log(f"ERROR this run broke on: {', '.join(broken)}")
            return 1
        return 0

    def one(self, file: Path) -> Result:
        """One playlist, start to finish."""
        cfg, log = self.cfg, self.log
        playlist = Playlist.from_file(file)
        for warning in playlist.warnings:
            log(f"WARN {warning}")
        if not playlist.entries:
            log("no tracks, skipped")
            return Result()
        entries = playlist.entries
        out_dir = cfg.output_dir / playlist.name
        before = playlist_status(entries, out_dir)
        tol = "off" if cfg.opts.length_tol < 0 else f"+-{cfg.opts.length_tol} s"
        log(f"{len(entries)} tracks, {len(before.have)} already here, "
            f"{len(before.missing)} missing, length tolerance {tol}")
        if not before.missing:
            log(f"nothing to search, all {len(entries)} track(s) are already in {out_dir}")
            return Result(total=len(entries))

        list_file = self.work_dir / f"{playlist.name}.list.txt"
        list_file.write_text("\n".join(e.list_line for e in before.missing) + "\n",
                             encoding="utf-8")
        client = cfg.client()
        log_file = self.verbose_log(playlist.name) if cfg.verbose else None
        cmd = client.command(list_file, out_dir, log_file)
        if cfg.dry_run:
            log("dry run: " + subprocess.list2cmdline(cmd))
            return Result(total=len(entries), missing=len(before.missing))
        out_dir.mkdir(parents=True, exist_ok=True)
        status = run_with_retry(cmd, cfg.app_dir, client.timeout_s, cfg.retries, log)
        if cfg.opts.preview:
            log("preview done" if status == OK else "FAILED")
            return Result(total=len(entries), missing=len(before.missing),
                          broke=status != OK)
        if status == ERROR:
            # the process never ran, so nothing is known about the network: saying a track is
            # missing here would be the tool blaming Soulseek for its own failure
            log("ERROR sockseek could not be started, nothing was searched")
            return Result(total=len(entries), missing=len(before.missing), broke=True)

        index_files = find_index_files(out_dir)
        rows, row_dirs = read_index_with_dirs(index_files)
        if not index_files:
            log(f"WARN no {INDEX_NAME} found under {out_dir}")
        after = playlist_status(entries, out_dir)
        arrived = [e for e in before.missing if e.original in after.files]
        still = [e for e in before.missing if e.original not in after.files]
        for entry in arrived:
            log(f"OK      {entry.original}")
        # A non-zero exit is the EVERYDAY case: sockseek returns it whenever one track fails
        # (run #0028 brought 6 of 10 and still exited 1). What marks a broken run is the
        # process being killed, or exiting non-zero with no index and nothing to show.
        broke = status == TIMEOUT and not arrived
        if broke:
            log("ERROR sockseek was killed by the timeout before anything arrived")
        elif status != OK and not arrived and not index_files:
            log("ERROR sockseek exited with an error and wrote no index: nothing was searched")
            broke = True
        if still and not broke:
            self.report(still, entries, rows, list_file, out_dir, client)
        log(f"run #{run_label(cfg.run_no)}: {len(arrived)} arrived, {len(still)} still missing, "
            f"{len(after.have)} of {len(entries)} in the folder")
        self.check_lengths(entries, rows, row_dirs)
        return Result(total=len(entries), missing=len(still), broke=broke)

    def report(self, still: list[Entry], entries: list[Entry], rows: list[dict],
               list_file: Path, out_dir: Path, client: Sockseek) -> None:
        """One FAILED line per track still missing, with the reason in words."""
        cfg, log = self.cfg, self.log
        by_line = rows_by_entry(entries, rows)
        failures = [failure_dict(e.original, by_line.get(e.original)) for e in still]
        found = (explain_failures(failures, entries, list_file, client, out_dir, log)
                 if cfg.explain else {})
        min_bitrate = read_min_bitrate(cfg.conf or cfg.sockseek.parent / SOCKSEEK_CONF)
        for entry, failure in zip(still, failures):
            if (failure["state"] or "").strip() in INDEX_OK:
                log("WARN the index says this one arrived, but no file is on disk: "
                    f"{failure['playlist_line']}")
            log(format_failure(failure))
            if cfg.explain:
                # the search string, which is what sockseek echoes as "Results for ...".
                # It equals the index title when there is a row, but a track with NO row used
                # to fall back to the playlist line with its " | 4:09" tail, and then nothing
                # could ever match: the log said "not checked" after paying for the search.
                for line in explain_failure(failure, found.get(entry.track.title),
                                            cfg.opts.length_tol, min_bitrate):
                    log(line)

    def check_lengths(self, entries: list[Entry], rows: list[dict], dirs: list[Path]) -> None:
        """The ffprobe report, only with --ffprobe-check. A missing ffprobe warns once."""
        cfg, log = self.cfg, self.log
        if not cfg.ffprobe_check:
            return
        if "path" not in cfg.ffprobe_state:
            cfg.ffprobe_state["path"] = quality.find_ffprobe(cfg.ffprobe)
            if cfg.ffprobe_state["path"] is None:
                log("WARN ffprobe not found, skipping the length check, pass --ffprobe PATH")
        ffprobe = cfg.ffprobe_state["path"]
        if ffprobe is not None and rows:
            quality.check_downloads(
                entries, rows, dirs, ffprobe, cfg.opts.length_tol, log,
                read_min_bitrate(cfg.conf or cfg.sockseek.parent / SOCKSEEK_CONF))

    def verbose_log(self, name: str, suffix: str = "") -> Path:
        tail = f"_{suffix}" if suffix else ""
        return self.logs_dir / f"sockseek_{run_label(self.cfg.run_no)}_{name}{tail}.log"


def run_batch(
    app_dir: Path,
    playlists_dir: Path,
    output_dir: Path,
    sockseek: Path,
    opts: Options = Options(),
    timeout_min: float = 40.0,
    retries: int = 2,
    dry_run: bool = False,
    only: Optional[str] = None,
    verbose: bool = False,
    explain: bool = True,
    ffprobe_check: bool = False,
    sockseek_conf: Optional[Path] = None,
    sockseek_args: tuple[str, ...] = (),
    config_report: tuple[str, ...] = (),
    early_messages: tuple[str, ...] = (),
    ffprobe: Optional[Path] = None,
) -> int:
    """Set up the folders, the run number and the log, then hand over to Batch.

    0 = the run worked (tracks may still be missing), 1 = this tool failed, 2 = setup error,
    130 = Ctrl+C.
    """
    cfg = RunConfig(
        app_dir=app_dir, playlists_dir=playlists_dir, output_dir=output_dir, sockseek=sockseek,
        opts=opts, timeout_min=timeout_min, retries=retries, dry_run=dry_run, only=only,
        verbose=verbose, explain=explain, ffprobe_check=ffprobe_check,
        sockseek_conf=sockseek_conf, sockseek_args=tuple(sockseek_args), ffprobe=ffprobe,
    )
    try:
        logs_dir = app_dir / "logs"
        work_dir = app_dir / "work"
        logs_dir.mkdir(exist_ok=True)
        work_dir.mkdir(exist_ok=True)
    except OSError as exc:
        print(f"ERROR: cannot create logs/work folders: {exc}", file=sys.stderr)
        return 2
    run_no, seq_warnings = next_run_number(logs_dir)  # written back before any download starts
    cfg = replace(cfg, run_no=run_no)
    log_path = logs_dir / f"run_{run_label(run_no)}_{cfg.stamp:%Y-%m-%d_%H-%M-%S}.log"

    def log(message: str) -> None:
        line = f"[{datetime.now():%H:%M:%S}] {message}"
        print(line, flush=True)
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass  # logging must never stop a download

    log(f"run #{run_label(run_no)}")  # the run number is the very first line
    for message in seq_warnings:
        log(message)
    for line in config_report:
        log(line)
    for message in early_messages:
        log(message)
    if not dry_run and not sockseek.is_file():
        log(f"ERROR: sockseek not found: {sockseek}")
        return 2
    # --no-config / --config in the passed-through arguments means the caller decides about
    # the config file (that is how the test suite runs sockseek in mock mode, with no login).
    decided = any(a == "--no-config" or a.startswith("--config") for a in cfg.sockseek_args)
    if sockseek_conf is not None and not sockseek_conf.is_file():
        log(f"ERROR: --sockseek-conf: no such file: {sockseek_conf}")
        return 2
    if not decided:
        conf = effective_conf(app_dir, work_dir, log, sockseek_conf)
        cfg = replace(cfg, conf=conf)
        absent = missing_credentials(conf.read_text(encoding="utf-8", errors="replace")
                                     if conf.is_file() else "")
        if absent and not dry_run:
            log(f"ERROR: no Soulseek login: {', '.join(absent)} missing in "
                f"{app_dir / SOCKSEEK_LOCAL_CONF}")
            return 2
    return Batch(cfg, logs_dir, work_dir, log).run()
