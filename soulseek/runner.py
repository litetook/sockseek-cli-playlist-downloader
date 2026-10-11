"""Driving sockseek.exe: the command line, the process, the retries.

One process per playlist. sockseek searches and downloads many tracks at once and has a single
search limiter (34 searches / 220 s) that protects the account from the server's 30-minute ban,
so starting several processes at once would defeat it. Slow uploaders are sockseek's job
(max-stale-time, downranking); this module only puts a wall clock on an attempt.
"""
from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .index import INDEX_NAME

# One flat folder per playlist; artist and title come from the search string or the tags.
NAME_FORMAT = "{artist( - )title|filename}"
RETRY_PAUSE_S = 10.0

# Outcome of one process
OK, FAILED, TIMEOUT, ERROR = "ok", "failed", "timeout", "error"


@dataclass(frozen=True)
class Options:
    """What the tool itself puts on the sockseek command line.

    Everything else - the quality floor, the format and bitrate preferences, the waiting
    windows - is sockseek's own and lives in sockseek.conf. A value here would silently beat
    that file, which is how `pref-min-bitrate` in the conf was dead until 2026-10-11.
    """
    length_tol: int = 3
    preview: bool = False


def build_command(
    sockseek: Path,
    list_file: Path,
    out_dir: Path,
    opts: Options = Options(),
    log_file: Optional[Path] = None,
    extra_args: tuple[str, ...] = (),
    index_name: str = INDEX_NAME,
    conf: Optional[Path] = None,
) -> list[str]:
    """The sockseek command for one list file.

    `conf` is the merged config (sockseek.conf + sockseek.local.conf, see settings) and is
    passed explicitly so sockseek cannot silently pick up a different file from %APPDATA%.
    It is left out when the caller already decides about the config itself.
    """
    cmd = [
        str(sockseek),
        str(list_file),
        "--input-type", "list",
        f"--length-tol={opts.length_tol}",  # "=" form: sockseek rejects "--length-tol -1"
        "-o", str(out_dir),
        "--name-format", NAME_FORMAT,
        "--index-path", str(out_dir / index_name),
    ]
    if opts.preview:
        cmd += ["--print", "results"]
    if log_file is not None:
        cmd += ["--verbose", "--log-file", str(log_file)]
    decided = any(a == "--no-config" or a.startswith("--config") for a in extra_args)
    if conf is not None and not decided:
        cmd += ["--config", str(conf)]
    cmd += list(extra_args)
    return cmd


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill the process and everything it started (taskkill /T on Windows)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc.kill()
    proc.wait()


def run_process(cmd: list[str], cwd: Path, timeout_s: Optional[float],
                log: Callable[[str], None]) -> str:
    """Run one process. OK, FAILED (non-zero exit), TIMEOUT (killed) or ERROR (cannot start).
    Ctrl+C kills the child and is re-raised."""
    try:
        proc = subprocess.Popen(cmd, cwd=cwd)
    except OSError as exc:
        log(f"cannot start: {exc}")
        return ERROR
    try:
        code = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        log(f"timeout after {timeout_s:.0f} s, process killed")
        return TIMEOUT
    except KeyboardInterrupt:
        kill_tree(proc)
        raise
    if code == 0:
        return OK
    log(f"exit code {code}")
    return FAILED


def run_with_retry(cmd: list[str], cwd: Path, timeout_s: Optional[float], retries: int,
                   log: Callable[[str], None], pause_s: float = RETRY_PAUSE_S) -> str:
    """Run cmd up to `retries` times; returns the status of the last attempt.

    The status, not a bool: sockseek exits non-zero whenever a single track fails, which is
    the normal case, while "could not start" and "killed by the timeout" mean the tool itself
    failed. Only the caller can tell those apart, so it gets the distinction.

    A retry earns tracks: on run #0002 an uploader that timed out on the first attempt
    delivered on the second.
    """
    status = ERROR
    for attempt in range(1, retries + 1):
        log(f"attempt {attempt}/{retries}")
        status = run_process(cmd, cwd, timeout_s, log)
        if status in (OK, ERROR):
            return status
        if attempt < retries:
            time.sleep(pause_s)
    return status


@dataclass(frozen=True)
class Sockseek:
    """The binary plus the few things the tool decides for it."""
    exe: Path
    cwd: Path
    opts: Options = Options()
    extra_args: tuple[str, ...] = ()
    timeout_min: float = 40.0
    retries: int = 2
    conf: Optional[Path] = None

    @property
    def timeout_s(self) -> Optional[float]:
        return self.timeout_min * 60 if self.timeout_min > 0 else None

    def command(self, list_file: Path, out_dir: Path, log_file: Optional[Path] = None,
                opts: Optional[Options] = None, index_name: str = INDEX_NAME) -> list[str]:
        return build_command(self.exe, list_file, out_dir, opts or self.opts, log_file,
                             self.extra_args, index_name, self.conf)

    def run(self, cmd: list[str], log: Callable[[str], None]) -> str:
        return run_with_retry(cmd, self.cwd, self.timeout_s, self.retries, log)

    def is_present(self) -> bool:
        return self.exe.is_file()
