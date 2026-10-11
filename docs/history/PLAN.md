# PLAN — Soulseek-Batch rewrite (2026-10-07)

Brief for the implementer. Everything marked **VERIFIED** was checked on this machine on
2026-10-07 by running `sockseek.exe` and reading the real run logs. Do not re-derive it, do not
"improve" on it, and do not contradict it.

Machine: LITEPC, Windows 11 Pro 10.0.26200, Python 3.13.14 (`py`).
App dir: `C:\claude_tasks\Soulseek-Batch`. `sockseek.exe` (114 MB) sits in that folder.

---

## 1. VERIFIED facts about sockseek.exe

Source: `sockseek.exe --help`, `--help notes`, `--help input`, `--help name-format`, plus two
live runs with `--mock-files-dir` (no Soulseek login needed).

### 1.1 Output layout

- With `--input-type list`, sockseek creates **one subfolder named after the list file stem**.
  `probe.list.txt` -> `<output>/probe.list/<files>` + `<output>/probe.list/_index.csv`.
- A single list file with 2 tracks puts **both files in that one subfolder** and runs the two
  searches **concurrently** (interleaved `[005]`/`[006]` lines in the log).
- `--name-format "{artist( - )title|filename}"` puts audio files **flat in `-o`**; `_index.csv`
  still lands in the `<stem>` subfolder. VERIFIED both ways.
- Defaults: `--concurrent-jobs 20`, `--concurrent-searches 2`.

### 1.2 Soulseek rate limit (this is what the owner asked about)

From `--help notes`: the Soulseek **server bans a user for 30 minutes** if too many searches
happen in a short timespan. sockseek has its own limiter, `--searches-per-time` (default **34**)
over `--searches-renew-time` (default **220** s). When its limit is reached, download status
becomes **`Waiting`** — that is the "queued" state.

=> 220 / 34 = **6.47 s per search** is the sustainable rate.

The limiter lives **inside one sockseek process**. A new process starts with a fresh budget, so
launching one process per track defeats it.

### 1.3 Stalls and slow uploaders

- `--max-stale-time` default **30000 ms** (30 s) — max time with no progress before giving up on
  a file and trying the next candidate.
- `--search-timeout` default **5000 ms**.
- `--max-retries` default **10** download retries per item; `--unknown-error-retries` default 2.
- `--fails-to-downrank` 1, `--fails-to-ignore` 2 — sockseek already downranks and then ignores
  uploaders that keep failing.
- `--fast-search-min-up-speed` exists for preferring faster uploaders.

=> Slow or dead uploaders are already sockseek's job. The old per-track hard kill duplicated it.

### 1.4 Index file `_index.csv`

Columns: `filepath,artist,album,title,length,tracktype,state,failurereason`.
VERIFIED on real data: **`state=1` = succeeded** (`failurereason=0`), **`state=2` = failed**
(every failure in the 2026-10-06 run had `failurereason=9`).
`--write-index` is on by default; `--index-path <path>` overrides its location.
`--skip-mode-output-dir index` is the default, so re-runs skip tracks already in the index.

### 1.5 List file format (`--input-type list`)

```
s:"artist=A, title=T, length=249"      "format=mp3; br>128"      "br >= 320"
```

Field 1 = input (`s:` prefix = song mode, `a:` = album). Field 2 = extra **required** conditions.
Field 3 = extra **preferred** conditions. Fields 2 and 3 are optional.
Accepted string properties: `title`, `artist`, `album`, `length` (seconds), `artist-maybe-wrong`,
`album-track-count`.

### 1.6 Conditions: hard vs soft — this matters

- `--length-tol <sec>` is a **hard** requirement, default **3**, `-1` disables it.
  `--pref-length-tol` is the soft one (default 3).
- `--min-bitrate` / `--format` are hard; `--pref-min-bitrate` (default 200) / `--pref-format`
  (default mp3) are soft.
- `--strict-title` / `--strict-artist` are hard; `--pref-strict-title` / `--pref-strict-artist`
  are soft (ranking only).

### 1.7 Useful flags for free-form SoundCloud-style titles

`--artist-maybe-wrong`, `-d/--desperate`, `--remove-brackets`, `--remove-ft`, `--regex <re>`,
`--extract-artist`, `--parse-title`, `--yt-dlp` (fallback download),
`--print results|jobs|index-failed`, `--progress-json`, `-v/--verbose`, `--log-file <path>`,
`--mock-files-dir <dir>` (simulate everything locally, no login — use this in tests).

---

## 2. VERIFIED facts about the current state of this app

- Yesterday's numbers: `soulseek_batch.ini` has `track_timeout = 200` (**seconds per track**) and
  `timeout = 180` (**minutes per attempt, batch mode only**). The owner remembered "180 sec per
  track"; there is no 180-second setting anywhere. `grep -rn 180` finds only `timeout = 180` and
  `DEFAULT_TIMEOUT_MIN = 180`. **The two ini keys mix units with no unit in the name.** Fixing
  that naming is part of this job.
- The 2026-10-06 22:14 run: 30 tracks, 3 passes, 16 failed, wall clock 22:14 -> 22:34. Every
  failure was `exit code 1` after ~6 s (consistent with `--search-timeout 5000`), and
  `state=2 failurereason=9` in the index. **No `timeout after ... s` line exists in any log file**
  (`grep -h "timeout after" logs/*.log` -> 0 hits), so the per-track hard-kill path has never
  fired in production.
- `output/cry-for-you-linds-edit-top30/` currently holds 30 `NNN.list/` subfolders with 14 audio
  files scattered one per folder. **Do not delete or move anything under `output/`.**
- `RUN_ME.bat` calls `download_all.ps1`, which does not exist.
- `sockseek.conf` sets `output-dir`, `length-tol = 6`, `pref-strict-title/artist`, `pref-format`,
  `pref-min-bitrate`. The script overrides `-o`, `--length-tol`, `--pref-format`,
  `--pref-min-bitrate` on the command line, so the conf values for those are dead.
  **`sockseek.conf` also holds the Soulseek username and password. Never print them, never copy
  them into another file, never commit them. Only edit comments and non-credential lines.**

---

## 3. Root cause of the two real problems

1. **Scattered output, no concurrency and rate-limit risk** all come from one decision: one
   sockseek process per track. It creates 30 list files, so sockseek makes 30 folders; it
   serialises work sockseek would do 20-wide; and it resets the search limiter 30 times, risking
   the server's 30-minute ban.
2. **16/30 failures** are a filtering problem, not a network problem: the script forced
   `--length-tol 1` (hard; sockseek default 3, owner's conf said 6) while `parse_duration`
   truncates fractional seconds (`4.9` -> `4`). Free-form remix titles plus a 1-second hard
   length window plus a 5-second search window leaves almost nothing.
   This is a **strong hypothesis, not proven** — `failurereason=9` is not documented anywhere.

---

## 4. What to build

Stdlib only. Python 3.13. `encoding="utf-8"` on every text read and write. All code, comments,
docstrings, help text and the tool readme in **English**.

### 4.1 `soulseek_batch.py` — rewrite

**Default mode becomes one sockseek process per playlist.** Keep a per-track mode as an explicit
escape hatch for debugging a single stubborn track; it is no longer the default.

| Option | Default | Notes |
|---|---|---|
| `--playlists PATH` | `./Playlists` | folder of playlist `.txt` files |
| `--output PATH` | `./output` | |
| `--sockseek PATH` | `./sockseek.exe` | |
| `--only NAME` | — | playlist stem |
| `--length-tol SEC` | `3` | hard condition; `-1` disables. **No longer 1.** |
| `--playlist-timeout MIN` | `60` | wall clock per attempt, `0` = none |
| `--retries N` | `2` | attempts per playlist |
| `--stale-time SEC` | `60` | `--max-stale-time`, `0` = sockseek default |
| `--search-timeout SEC` | `0` | `0` = sockseek default (5 s) |
| `--item-retries N` | `0` | `0` = sockseek default (10) |
| `--searches-per-time N` | `0` | `0` = sockseek default (34) |
| `--searches-renew-time SEC` | `0` | `0` = sockseek default (220) |
| `--concurrent-searches N` | `0` | `0` = sockseek default (2) |
| `--strict` | off | `--strict-conditions` |
| `--desperate` | off | `-d` |
| `--artist-maybe-wrong` | off | |
| `--remove-brackets` | off | |
| `--remove-ft` | off | |
| `--fast-search` | off | |
| `--nested` | off | keep sockseek's `<stem>/` subfolder; default is flat |
| `--split-artist` | off | as before |
| `--per-track` | off | escape hatch: one process per track |
| `--track-timeout SEC` | `300` | only with `--per-track`, `0` = none |
| `--passes N` | `1` | only with `--per-track` |
| `--pause SEC` | `7` | only with `--per-track`; see 4.3 |
| `--dry-run` | off | write list files, print commands, run nothing |
| `--preview` | off | `--print results` |
| `--verbose` | off | sockseek `--verbose` + `--log-file logs/sockseek_<name>_<stamp>.log` |
| `--config PATH` | `./soulseek_batch.ini` | |

Flat output is `--name-format "{artist( - )title|filename}"` plus
`--index-path <output>/<name>/_index.csv`. **Verify with `--mock-files-dir` that the index really
lands there.** If `--index-path` turns out not to work that way, keep sockseek's default index
location and find it by globbing `<output>/<name>/**/_index.csv`. Write down in the readme which
of the two you ended up with, and that you tested it.

Exit codes stay: `0` all good, `1` something failed, `2` setup error, `130` Ctrl+C.

**Log the effective configuration as the first lines of every run**, one key per line, with the
unit in the key name and the source of each value (`ini`, `cli`, `default`). This is a hard
requirement — the owner must be able to answer "where is this number written?" from the log alone.

### 4.2 Failure reporting from the index, not from exit codes

After a playlist finishes, read its `_index.csv` and write
`logs/failed_<name>_<stamp>.csv` with columns
`playlist_line,index_title,index_length,state,failurereason`.
Rows with `state != 1` are failures. Match index rows back to playlist lines by position where
possible; otherwise leave `playlist_line` empty rather than guessing.
State the raw-code caveat in the readme: only `1 = ok` and `2 = failed` are confirmed.
Use the stdlib `csv` module — titles contain commas, so never split on `,` by hand.

### 4.3 Rate limiting

- Default mode: one process, one limiter — nothing extra to do, but the readme must state the
  30-minute ban and the `Waiting` status.
- `--per-track` mode: every new process resets the limiter, so enforce the pause ourselves.
  `--pause` default **7 s** (220 / 34 = 6.47, rounded up). Log a warning when per-track mode
  starts, explaining why the pause exists and that lowering it risks a 30-minute ban.

### 4.4 Fix these specific defects from the review

1. Validate ranges in `load_config` and after `parse_args`: reject negatives for `passes`,
   `retries`, `length_tol` (except `-1`), every timeout, and `pause`. `passes = -1` currently
   makes the batch silently download nothing — it must be rejected with a clear message or
   clamped to 0, and either way logged.
2. `parse_duration`: round, do not truncate (`4.9` -> 5). Keep returning `None` for junk.
3. The per-track `ERROR` path must not report tracks that already succeeded in the same pass as
   failed. Report only what is genuinely still pending.
4. `--only NAME` with no match must say `no playlist named '<NAME>' in <dir>`, not
   "no playlist .txt files".
5. Encoding fallback wording: when a file decodes as cp1251 only because UTF-8 failed, say
   "not valid UTF-8, decoded as cp1251 — check the file". The current wording claims to know the
   encoding is cp1251, which it does not.
6. De-duplicate identical playlist lines and log how many duplicates were dropped.
7. `run.cmd`: propagate the exit code and only `pause` when double-clicked:

   ```
   @echo off
   cd /d "%~dp0"
   py soulseek_batch.py %*
   set RC=%ERRORLEVEL%
   if "%~1"=="" pause
   exit /b %RC%
   ```

### 4.5 `soulseek_batch.ini` — regenerate with units in the key names

New keys, each carrying its unit: `length_tol_s`, `playlist_timeout_min`, `retries`,
`stale_time_s`, `search_timeout_s`, `item_retries`, `searches_per_time`,
`searches_renew_time_s`, `concurrent_searches`, `strict`, `desperate`, `artist_maybe_wrong`,
`remove_brackets`, `remove_ft`, `fast_search`, `nested`, `split_artist`, `per_track`,
`track_timeout_s`, `passes`, `pause_s`.

On load, accept the **old** key names too (`tol`, `timeout`, `track_timeout`, `stale_time`) and
print a one-line deprecation warning naming the new key. The file on disk has
`track_timeout = 200` and `timeout = 180`; those must keep working and map to
`track_timeout_s = 200` and `playlist_timeout_min = 180`.

### 4.6 `tools/flatten_output.py` — new

One-time migration for the existing scattered downloads. Moves audio files from
`<output>/<name>/NNN.list/` up into `<output>/<name>/`, leaves `_index.csv` files alone, refuses
to overwrite, and `--dry-run` is the **default** — `--apply` is required to move anything.
**Do not run it.** The owner runs it.

### 4.7 Delete

`RUN_ME.bat`, `README.txt`, `tracks_cry-for-you-linds-edit-style.txt`,
`tracks_cry-for-you-linds-edit-top30.txt`, and the regenerable contents of `work/`.
Keep `logs/`, `output/`, `sockseek.exe`, `sockseek.conf`.

### 4.8 `sockseek.conf` — minimal edit only

Translate the comments to English. Delete only the lines the script now always passes itself
(`output-dir`, `length-tol`, `pref-format`, `pref-min-bitrate`) and add a comment saying the
script owns them. Keep `pref-strict-title` and `pref-strict-artist`.
**Leave `username` and `password` exactly as they are, byte for byte.**

### 4.9 `docs/README.md` (English, tool usage) — new, replaces `README.txt`

Must cover: installing sockseek, credentials in `sockseek.conf`, playlist format, how to run
(`run.cmd` or `py soulseek_batch.py`), where files land, the ini keys and their units, the
Soulseek 30-minute ban and the `Waiting` status, what to do when tracks are not found (raise
`--length-tol`, try `--artist-maybe-wrong`, `--desperate`, `--remove-brackets`, use `--preview`
to see what the search actually returns), and how to read `logs/failed_*.csv`.

---

## 5. Tests — `test_soulseek_batch.py`

Keep unit tests for the pure functions. **Replace the fake `.cmd` sockseek with the real
`sockseek.exe` driven by `--mock-files-dir`**, so the tests exercise the real binary with no
login and no network. Skip those tests with `unittest.skipUnless` when `sockseek.exe` is absent.

Required new cases, each tied to a defect above:

1. One list file with 2 tracks -> both audio files land **flat** in `<output>/<name>/`, and the
   test asserts there is **no** `NNN.list` subfolder containing audio.
2. `_index.csv` is found and parsed; a mock run with one deliberately missing track produces a
   `logs/failed_*.csv` holding exactly that one row.
3. `--only nosuch` exits 2 and the message names the playlist.
4. `passes = -1` in the ini does not silently download nothing.
5. `parse_duration("4.9") == 5`.
6. Duplicate playlist lines collapse to one entry.
7. `--per-track` mode still works and respects `--pause 0` in tests.
8. Old ini key names (`tol`, `timeout`, `track_timeout`) still load and warn.
9. The effective-configuration block appears in the log with units and sources.

Keep the existing encoding, Ctrl+C, and per-playlist-`OSError` tests.

Owner's standing rule: **basic scenarios only** — no mass, property-based or mutation testing.

---

## 6. Constraints

- Never run `sockseek.exe` against the real Soulseek server. `--mock-files-dir` with `--no-config`
  only. One stray real run can earn a 30-minute ban.
- Do not touch anything under `output/` or `logs/`.
- Do not print, copy or commit the contents of `sockseek.conf`.
- Do not `git commit` or `git push` — `C:\claude_tasks\_tools\hub.py` does that.
- Leave `C:\claude_tasks\Soulseek-Batch\README.md` (the hub task file, Ukrainian) alone; the
  reviewer writes it. The tool's English readme is a separate file at `docs/README.md`.

## 7. Definition of done

- `py -m unittest test_soulseek_batch -v` passes; paste the final counts.
- `py soulseek_batch.py --dry-run` on the existing `Playlists/` prints the command it would run
  and the effective-configuration block; paste both.
- `py soulseek_batch.py --help` output pasted.
- Every file listed in 4.7 is gone; every file listed in 4.1-4.9 exists.
- A short list of anything you could not do, or had to decide differently, and why.
