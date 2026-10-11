# PLAN2 — addendum approved by the owner on 2026-10-07 10:40

Read `PLAN.md` first: its section 1 holds the verified facts about `sockseek.exe` and still applies
in full. This file adds five changes the owner approved and nothing else. Same hard constraints as
`PLAN.md` section 6 (stdlib only, English, `encoding="utf-8"`, never run sockseek against the real
Soulseek server, never touch `output/` or `logs/`, never read or print `sockseek.conf`, no commits).

New verified facts behind these changes, established 2026-10-07 by measuring the owner's 14
downloaded files with `C:\ffmpeg\bin\ffprobe`:

- The `length` column of `_index.csv` is the length **from the playlist line**, not a measured one.
  Comparing it against the playlist gives a difference of 0 for every row by construction. It
  proves nothing about the file on disk.
- One of the 14 files is **49 s shorter** than its playlist line asked for (want 262, real 213) and
  is a different edit of the track. It passed because, per `--help file-conditions`, sockseek
  "accepts common audio files with **no length metadata**" — when the peer reports no length, the
  `--length-tol` filter does not apply at all.
- Four of the 14 files are below 320 kbps, one at **83 kbps**, because `--pref-min-bitrate` only
  ranks and never rejects.

## 1. `stale_time_s`: 60 -> 30

In `soulseek_batch.ini` only. 30 is also sockseek's own default for `--max-stale-time`.

## 2. `fast_search`: false -> true

In `soulseek_batch.ini` only. The code already supports the flag.

## 3. Remove the failed CSV — failures go into the run log

Delete `write_failed_csv` and `FAILED_COLUMNS`, and stop writing `logs/failed_<name>_<stamp>.csv`.
Keep `failure_rows` and `match_index`: they still produce the data, it is only rendered differently.

Render one log line per failed track:

```
FAILED  state=2 reason=9  Funk Tribu - September - Cry For You (Funk Tribu Rework) | 5:37
```

When a failed index row matches no playlist line, say so instead of guessing:

```
FAILED  state=2 reason=9  (no matching playlist line, index title: Some Title)
```

Then one summary line naming the run number from change 4:

```
FAILED 16/30 track(s) in run #0043
```

The existing WARN about failed index rows that match no line in this playlist stays.

## 4. Run sequence number

- State file `logs/run_seq.txt`, UTF-8, holding a single integer: the last number used.
- At the start of a run: read it, add 1, write it back immediately (before any download), and use
  that number for this run.
- If the file is missing, empty or not an integer: recover by scanning `logs/` for
  `run_<digits>_*.log` and taking the highest number found plus 1, else 1. Log one WARN saying the
  counter was rebuilt. Never crash on it; if `logs/` cannot be written, log a WARN and fall back to
  number 0 so the run still proceeds.
- Log file name becomes `logs/run_<NNNN>_<YYYY-MM-DD_HH-MM-SS>.log`, zero-padded to 4 digits.
  Numbers past 9999 simply get longer; do not wrap.
- The **first** line of every log is the run number, before the effective-configuration block:
  `run #0043`.
- The final summary line repeats it, so a run can be referred to by number alone.
- With `--verbose`, sockseek's own log becomes `logs/sockseek_<NNNN>_<name>.log`.

## 5. Verify the downloaded files with ffprobe, report only

A new step that runs after a playlist finishes (not in `--dry-run`, not with `--preview`).

**Finding ffprobe.** New CLI option `--ffprobe PATH` and ini key `ffprobe_path` (empty = auto).
Auto-detection order: `ffprobe` on `PATH`, then `C:\ffmpeg\bin\ffprobe.exe` (it is there on this
machine). If none is found, log exactly one WARN (`ffprobe not found, skipping the length check,
set ffprobe_path in soulseek_batch.ini`) and skip the step. A missing ffprobe is **not** an error
and must not change the exit code.

**What to measure.** Walk the index rows whose state is in `INDEX_OK` and whose `filepath` is not
empty. Resolve `filepath` relative to the folder holding that `_index.csv`. For each resolved file
that exists, run:

```
ffprobe -v error -show_entries format=duration,bit_rate -of csv=p=0 <file>
```

Parse `duration` (float seconds, round to int) and `bit_rate` (bits per second, report as kbps).
Use a 30 s timeout per call so a corrupt file cannot hang the run, and treat any failure to parse
as "unknown" rather than an error.

**What to compare.** Use `match_index` to get the playlist entry behind each row, and compare the
measured duration with that entry's `track.length`:

- Entry has a length and `length_tol_s >= 0`: flag the file when `abs(real - want) > length_tol_s`.
- Entry has no length, or `length_tol_s` is `-1`: print the numbers, never flag.

**What to log.** One line per measured file, then a summary:

```
CHECK  want=262 real=213 diff=-49 br=323kbps  MISMATCH  09. September - Cry For You (...).mp3
CHECK  want=277 real=277 diff=+0  br=2304kbps  Armin Hermann - We No Speak Americano (EDIT).wav
CHECK 2 of 14 file(s) outside +-3 s: 09. September - ... .mp3, Kate Ryan- ... .wav
```

Always print the real bitrate, since it is information the owner wants, but **never** add
`--min-bitrate` to the sockseek command and never flag a file for its bitrate alone — the owner
explicitly declined a hard bitrate requirement, because sockseek's own help warns that
`--strict-conditions` with `--min-bitrate` discards every share from standard Soulseek clients.

**What NOT to do.** Do not move, rename, quarantine or delete any file. Do not change the exit code
because of a mismatch. The owner asked for a flag in the log and nothing more.

## 6. Tests

Update `test_soulseek_batch.py` for all of the above, keeping the existing coverage green and the
suite under about 60 s. New cases, basic scenarios only:

- A failed track is listed in the run log, and **no** `failed_*.csv` is created anywhere.
- `logs/run_seq.txt` increments across two runs, and the log file names carry the numbers.
- A corrupt or missing `run_seq.txt` is rebuilt from the existing log file names, with a WARN.
- `run #NNNN` is the first line of the log, before the configuration block.
- The ffprobe step flags a file whose real duration is outside the tolerance and leaves it on disk.
  Generate the audio under test with the ffmpeg that is already installed
  (`C:\ffmpeg\bin\ffmpeg.exe -f lavfi -i anullsrc -t <seconds> <out.mp3>`) so you have files of a
  known duration; skip the case with `unittest.skipUnless` when ffmpeg or ffprobe is absent.
- A missing ffprobe only warns and does not change the exit code.
- The bitrate is reported but never flags a file and never reaches the sockseek command line.

## 7. Documentation

Update `docs/README.md`: the failed CSV section becomes the log format, add the run number and the
`run_seq.txt` file, add the ffprobe check with its `--ffprobe` / `ffprobe_path` setting, and record
the three new verified facts from the top of this file (the `_index.csv` `length` column is the
requested length, not a measured one; files with no length metadata bypass `--length-tol`
entirely; `--pref-min-bitrate` never rejects). State plainly that the length check is a report and
changes nothing on disk. Leave `README.md` at the repository root alone — the reviewer owns it.

## 8. Definition of done

- `py -m unittest test_soulseek_batch -v` passes; paste the counts.
- `py soulseek_batch.py --dry-run` still exits 0; paste its first three lines so the run number and
  the configuration block are visible.
- Paste a real log from a mock run that shows the `FAILED` lines and the `CHECK` lines together.
- A short list of anything you could not do or decided differently, and why.
