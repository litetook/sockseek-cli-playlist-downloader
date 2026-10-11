# sockseek CLI playlist downloader - reference

Downloads playlists from Soulseek by driving [sockseek](https://github.com/fiso64/sockseek).
You give it text files with `Artist - Title | 4:09` lines; it shows what of each playlist is
already on disk, searches **only what is missing** after you say yes, runs **one sockseek process
per playlist**, and reports what did not arrive and why.

The one command is `py run.py`. Re-running the same playlist later is the normal workflow: what
arrives depends on who is online right now, not on settings (section 8).

Requirements: Python 3.10+ and a sockseek build for your system. Standard library only, nothing to `pip install`. Developed and measured on Windows; macOS is untested so far.

## 0. What is where

```
run.cmd / run.sh       launchers: find Python, hand over to run.py (Windows / macOS, Linux)
run.py                 the one command: menu, status, confirmation, --import
soulseek/
    settings.py        config.yaml, the folders, the tunable numbers, sockseek.conf lookups
    playlist.py        playlist files -> entries
    importing.py       an exported list (m3u/csv/text) -> a playlist file
    index.py           sockseek's _index.csv: what is on disk, what failed and why
    runner.py          building and running the sockseek command
    explain.py         the extra conditionless search that explains every failure
    quality.py         the optional ffprobe report
    batch.py           the run itself
    cli.py             the engine's command line
tests/                 one test module per component, plus support.py
config.yaml            this tool's settings (section 5)
sockseek.conf          every sockseek option, no secrets - publishable (section 7)
sockseek.local.conf    your Soulseek login and any override of the above - git-ignored
README.md              the project page: purpose, quick start, how it works
TASK.md                the development log in Ukrainian: measurements, traps, what is unproven
Playlists/ output/ work/ logs/   input, downloads, generated list files, run logs
docs/history/          finished plans and handovers, kept for the record
```

## 1. Install

1. Download `sockseek.exe` from <https://github.com/fiso64/sockseek/releases> and put it in the
   same folder as `run.py` (or point to it with `paths.sockseek` in `config.yaml`).
2. Put your Soulseek login into **`sockseek.local.conf`** (the first run creates it from a
   placeholder template):

   ```
   username = your_login
   password = your_password
   ```

   That file is the only one that holds secrets, it is git-ignored, and nothing in the logs ever
   prints its values. It also overrides any other key of `sockseek.conf` (section 7), which is
   what a setup script would write into it. Without a login the run stops with a message instead
   of failing inside sockseek.
3. Put playlist files into `Playlists/` (next section).

`sockseek.conf` holds every quality and waiting knob (section 7) and **no credentials**, so it
can be published. The keys `output-dir`, `length-tol`, `name-format` and `index-path` are
deliberately not in it either: the script passes those on every run, so a value in the conf
would be dead.

## 2. Playlist format

One `.txt` file per playlist in `Playlists/`. The file name (without `.txt`) is the playlist name
and becomes the output folder name. One track per line:

```
Artist - Title | 4:09
Some Track (Remix) | 5:37
```

- The part after `|` is the length (`m:ss`, `h:mm:ss`, or plain seconds). Fractional seconds are
  **rounded**, not truncated (`4.9` is 5). It is passed to sockseek and used as a **hard** filter
  with the tolerance set by `--length-tol`. A line with no length searches without a length filter.
- Lines starting with `#` and blank lines are ignored.
- Identical lines inside one playlist are collapsed to one; the run log says how many were dropped.
- Encoding: UTF-8. If a file is not valid UTF-8 it is decoded as cp1251 and the log says
  "not valid UTF-8, decoded as cp1251 - check the file". Fix the file rather than rely on that.

### Importing a list someone else exported

A playlist can be written by hand, but it can also come out of another program:

```
py run.py --import "C:\exports\my set.m3u8"
py run.py --import tracks.csv --as techno-2026
py run.py --import tracks.csv --as techno-2026 --overwrite
```

Recognised by extension or content:

| Format | Where the length comes from |
|---|---|
| `.m3u`, `.m3u8` | `#EXTINF:249,Artist - Title`, in **seconds** (`-1` = unknown) |
| `.csv`, `.tsv` with a header | a duration column: `Duration (ms)`, `duration`, `time`, `length`. Milliseconds are recognised by the column name and by a value too large to be seconds |
| any other text | one name per line, no lengths |

The title column is looked up among `Track Name`, `title`, `name`, `track`, `song`; the artist
among `Artist Name(s)`, `artist`, `artists`, `album artist`. Everything else in the file is
ignored, and anything skipped is named in a `WARN` line.

An existing playlist is **not** replaced without `--overwrite`: a playlist is hand-edited, and
silently overwriting one would throw that work away. A link (Spotify, SoundCloud, Beatport) is a
separate input interface and is not implemented.

## 3. Run

```
py run.py                              rem THE command: pick, see what is missing, confirm
py run.py --only my-playlist           rem skip the menu (file stem, no .txt)
py run.py --only my-playlist --yes     rem skip the confirmation too (scheduled runs)
py run.py --only my-playlist --dry-run rem print the sockseek command, run nothing
py -m soulseek.cli --help              rem the engine options; run.py passes them through
```

Nothing is downloaded until the second yes:

```
Playlists:

  #  playlist                      tracks  here  missing
  -  ----------------------------  ------  ----  -------
  1  cry-for-you-linds-edit-top30      30    15       15

What to download? (1, or 1,2, or all; Enter quits): 1

cry-for-you-linds-edit-top30: 30 tracks, 15 here, 15 missing

Missing:
   1  Hung Up (Benleh Remix) | 4:51
   2  Arman John - Paradisio - Bailando (Arman John Edit) | 10:04
   ...

Download these 15? [y] yes  [n] no:
```

"here" means one thing only: sockseek's index has a row for that line saying it arrived (state 1
or 3) AND the file is really on disk. An index row whose file was deleted reads as missing again.
File names alone cannot be used for this: they come from the uploader
(`... (Clean) 1A 142 [www.dj-promo.org].mp3`) and no longer carry the playlist line.

`run.cmd` is a thin shim around `py run.py`; it pauses at the end only when double-clicked.

**Exit code `1` means this tool failed, not that a track is unavailable.** A track nobody shares
is news about Soulseek, and on a playlist of SoundCloud edits it is the normal case; it is
reported in the log and in the missing list, and the run still ends with `0`.

| Code | Meaning |
|---|---|
| `0` | the run worked. Some tracks may be missing; the summary line says how many |
| `1` | the run broke: sockseek reported errors, timed out, or a playlist could not be read |
| `2` | setup error: bad option, missing `sockseek.exe`, unknown `--only` name |
| `130` | Ctrl+C |

### One pass, one window

There is a single set of conditions for every track: the length window (`length_tol_s`, 45 s) and
`min-bitrate 256` from `sockseek.conf`. Nothing else filters.

45 s, not sockseek's default 3, because the lengths in a SoundCloud playlist are systematically
SHORTER than the copies people share - 319 s in the list against 346 s on the network for the
same remix (measured 2026-10-07). A 3 s window rejects the very file you asked for.

What keeps *another version* of the song out is not a name condition but the search itself:
Soulseek requires every word of the query to appear in the file path, and the query carries the
`(... Remix)` / `(... Edit)` tag, so the plain original cannot match. Across 13 candidates seen
on 5 tracks, not one wrong version came back.

Do not reach for `--strict-title`. Measured on the full playlist: `+-45 s` plus
`--extract-artist --strict-title` lets **6 of 30** tracks through where the plain window lets
**15**. It rejects even file names that contain the title literally, and marks every candidate
`StrictTitle fails`.

The length check (section 9) never changes the exit code, and neither does a missing `ffprobe`.

Every run ends with one summary line:

```
15 of 30 track(s) downloaded, 15 missing (run #0002)
```

Tracks already in a playlist's `_index.csv` are skipped by sockseek (`--skip-mode-output-dir index`
is its default), so re-running only retries what is missing. The missing lines are also written
out as a playlist of their own (section 8), so the next run can be just that.

## 4. Where files land

| Path | What |
|---|---|
| `output/<name>/` | downloaded audio, flat, named `Artist - Title.ext` |
| `output/<name>/_index.csv` | sockseek's index for that playlist: the only link between a playlist line and a file (section 8) |
| `work/` | generated sockseek list files, rebuilt on every run, safe to delete |
| `logs/run_<NNNN>_<stamp>.log` | the script's log; **first line is `run #NNNN`, then the effective configuration**. `<stamp>` is `YYYY-MM-DD_HH-MM-SS` |
| `logs/run_seq.txt` | the run counter, one integer: the last run number used |
| `logs/sockseek_<NNNN>_<name>.log` | sockseek's own verbose log (only with `--verbose`) |

Failed tracks are listed inside the run log, as `FAILED` lines (section 8). There is no
separate failure file.

Flat output is `--name-format "{artist( - )title|filename}"` plus
`--index-path <output>/<name>/_index.csv`. That `--index-path` was verified with
`--mock-files-dir` on 2026-10-07: the index really does land at exactly that path. Indexes left
by older versions, which wrote one per sub-folder, are still found by globbing
`<output>/<name>/**/_index.csv` as a fallback.

### Run number

Every run gets a number, so you can say "run 43" instead of quoting a timestamp.

- `logs/run_seq.txt` holds a single integer: the last number used. At the start of a run the
  script reads it, adds 1 and writes it back **before any download**, then uses that number.
- The log file is `logs/run_<NNNN>_<YYYY-MM-DD_HH-MM-SS>.log`, zero-padded to 4 digits. Past
  9999 the number just gets longer; it does not wrap.
- The **first line** of the log is `run #0043` (before the configuration block), and the final
  summary line repeats it. With `--verbose`, sockseek's log is `logs/sockseek_0043_<name>.log`.
- If `run_seq.txt` is missing, empty or not an integer, the script rebuilds the counter: it scans
  `logs/` for `run_<digits>_*.log`, takes the highest number found plus 1 (or 1 if there are
  none), and logs one WARN saying the counter was rebuilt. It never crashes on this. If `logs/`
  cannot be written at all, it logs a WARN and uses run number 0 so the run still proceeds.
- So deleting `run_seq.txt` is harmless as long as the old log files are still there. If you
  delete the logs **and** the counter, numbering starts again at 1.

## 5. Settings: `config.yaml`

There are **two** configuration files, and the split is the whole point:

| File | Holds | Who reads it |
|---|---|---|
| `config.yaml` | the folders and the three values this script needs itself | this script |
| `sockseek.conf` | the Soulseek login and every sockseek option | sockseek |

The file carries **no comments** - it is a list of names and values, and this section is where
they are explained (owner's call, 2026-10-11):

```yaml
paths:
  sockseek: sockseek.exe
  playlists: Playlists
  output: output

search:
  length_tol_s: 45
  retries: 1
  playlist_timeout_min: 10
```

A relative path is relative to the folder holding `run.py`, so the defaults above are
exactly the layout inside the project; an absolute path (`output: D:\music`) is taken as it is.
Precedence: **command line > config.yaml > built-in default**. After the `run #NNNN` line every
run log lists the effective values with their source (`cli`, `config`, `default`), so "where does
this number come from?" is always answered by the log.

| key | CLI option | Default | Meaning |
|---|---|---|---|
| `paths.sockseek` | `--sockseek` | `sockseek.exe` | the sockseek binary |
| `paths.playlists` | `--playlists` | `Playlists` | folder of playlist `.txt` files |
| `paths.output` | `--output` | `output` | where the audio and the index go |
| `search.length_tol_s` | `--length-tol` | `45` | **seconds**, hard filter around the length in the playlist; `-1` disables. 45 because playlist lengths run short of the shared copies (section 3) |
| `search.retries` | `--retries` | `2`, **`1` in the shipped file** | attempts per playlist. A retry re-searches what is still missing; it earned a track on run #0002, but it also doubles the wall clock, which is why the shipped file asks for one attempt |
| `search.playlist_timeout_min` | `--playlist-timeout` | `40`, **`10` in the shipped file** | **MINUTES**, wall clock **per playlist attempt**; `0` = none. 10 because a real 30-track run takes about 6 minutes and anything past that is waiting for nothing |

The parser is deliberately not a YAML implementation: it reads `key: value` lines at any
indentation, ignores section names, tolerates `#` comments and quotes, and reports anything it
does not recognise as an unknown key. Lists and deeper nesting are not supported.

Unknown keys, invalid values and values below the legal minimum are each named in a `WARN` line
and then ignored, so a typo never silently changes a run. Old key names (`tol`, `timeout`) are
still accepted with a deprecation warning. `ffprobe` is a command-line option only
(`--ffprobe PATH`), because the check it belongs to is off by default (section 9).

**Migration from `soulseek_batch.ini`.** On the first run without a `config.yaml`, an old ini next
to it is read, its three values are carried into the new file, and the ini is renamed to
`soulseek_batch.ini.migrated`. The log says so in one `WARN` line. Nothing is lost and nothing has
to be done by hand.

Other options (CLI only): `--only NAME`, `--config PATH`, `--dry-run`, `--preview`, `--verbose`,
`--no-explain`, `--ffprobe-check`, `--ffprobe PATH`. `run.py` adds `--yes` and passes everything
else through to the engine untouched.

`--sockseek-args="<args>"` appends raw arguments to every sockseek command. This is the way to
try a sockseek option once without editing `sockseek.conf`:

```
py run.py --only my-playlist --sockseek-args="--desperate --artist-maybe-wrong"
```

The string is split like a shell would split it, and it is also how the test suite injects
`--mock-files-dir`. Anything passed here reaches sockseek unchecked, so a typo surfaces as a
sockseek error, not a Python one.

### The unit trap

**`playlist_timeout_min` is MINUTES, and applies per playlist attempt.** With
`playlist_timeout_min = 40` and `retries = 2`, one playlist can run for up to 2 x 40 minutes
before the script gives up. It is a wall-clock limit on the whole sockseek process for that
playlist, not on one track. There is no per-track limit at all: sockseek handles slow or dead
uploaders itself (`max-stale-time` in `sockseek.conf`, 30 s as shipped, after which it downranks
and finally ignores uploaders that keep failing).

## 6. The Soulseek 30-minute ban and the `Waiting` status

The Soulseek **server bans a user for 30 minutes** if too many searches are made in a short
time. sockseek has its own limiter to stay under that: by default **34 searches per 220 seconds**
(`searches_per_time`, `searches_renew_time_s`). That is one search every 220 / 34 = **6.47 s**.

When the limiter is reached, sockseek does not fail: the affected tracks get the status
**`Waiting`** (this is the "queued" state) and start as soon as the window renews. Seeing
`Waiting` for a few minutes on a big playlist is normal and not a hang.

Consequences:

- **The limiter lives inside one sockseek process.** That is why the default mode runs one process
  per playlist: all tracks share one budget. A new process starts with a fresh budget.
- **Each attempt is a new process, so `retries = 2` means two logins and two fresh budgets.**
  Observed on run #0002: `Logging in as <your-login>` twice, 30 searches in the first attempt and 15 in
  the second. The server saw 45 searches in 6 minutes and did not complain, but the limiter
  inside sockseek only protects one process at a time - raising `retries` raises the real risk.
- Do not run two copies of the script at once, and do not raise `searches_per_time` above
  sockseek's default unless you know what you are doing. A ban cannot be lifted from the client;
  you can only wait it out.

## 7. sockseek's own options: `sockseek.conf`

Same directory, same names as sockseek's command-line options without the leading `--`, same
units. `sockseek.exe --help` is the reference, and `--help config` documents the file itself.
Unknown keys and bad values are rejected on startup, so a typo is loud, not silent (verified:
a broken value gives `Option '--max-stale-time' requires an integer`, an unknown key gives
`Unknown argument`).

The file carries no comments and no login; this section explains the keys.

```
max-stale-time = 300000

min-bitrate = 256
pref-min-bitrate = 320
pref-max-bitrate = 1000000
pref-format = flac,wav,mp3

fast-search = true
pref-strict-title = true
pref-strict-artist = true
```

**Quality.** `min-bitrate = 256` is the only hard floor (owner's call 2026-10-07: "256 is the
baseline minimum"). A hard maximum is deliberately **not set at all - unlimited** (owner,
2026-10-11); to cap it, add `max-bitrate = N`. `pref-*` keys only rank, they never reject:
`pref-max-bitrate = 1000000` exists purely to lift sockseek's own default ranking cap of **2500
kbps**, which quietly ranked 24-bit lossless BELOW an mp3 320. Do not enable
`strict-conditions`: together with `min-bitrate` it discards every share from the standard
Soulseek client, which does not broadcast a bitrate at all - which is also why a file can slip
through below the floor.

**Waiting.** `max-stale-time` is milliseconds without transfer activity before a candidate is
dropped. Back to **30000 (30 s)** on 2026-10-11, measured: with 300000 (5 min) run #0026 spent
25 minutes on 15 tracks and brought **zero** - those uploaders do not deliver at all, they are
not merely slow. The 5-minute window only made every failure five times more expensive. sockseek
never logs a queue position and has no separate option for queued transfers, so this window
cannot tell "queued" from "stuck" either way.

**Picking fast uploaders.** `fast-search` takes the first candidate that satisfies the preferred
conditions instead of waiting for the whole search, and two keys shape that choice:

- `fast-search-delay = 2000` - milliseconds spent collecting candidates before accepting one
  (sockseek's default is 300, which often means "whoever answered first");
- `fast-search-min-up-speed = 200` - a candidate's reported upload speed must reach this, a
  pass mark meant to skip the uploaders that never deliver. **To switch it off, set it to 1**,
  which is sockseek's own default and accepts anybody.

The unit is not documented. It is **not** MB/s: with the default of 1 a candidate reported at
0.02 MB/s was still accepted (runs of 2026-10-07), so 200 is either 200 kB/s - which skips
exactly those - or 200 B/s, which changes nothing. Harmless either way, and worth re-measuring.

There is **no** ranking by speed in sockseek: the search output prints each candidate's speed
(`(0.02MB/s)`, `(6.29MB/s)`), but nothing sorts on it. Choosing the fastest of all candidates
would need a different design - search without downloading, pick, then fetch by `slsk://` link.

**The layers.** sockseek reads exactly one config file and has no `include`, so the tool merges
them itself into `work/sockseek.effective.conf` and passes `--config` pointing at it:

```
sockseek.conf  <  sockseek.local.conf  <  --sockseek-conf FILE
```

Lowest to highest. Every layer has the same syntax and may hold as few keys as it likes; a key
replaces the same key of a lower layer, a new key is appended, and a `[profile]` section is
copied untouched. The published file keeps `username` and `password` commented out rather than
empty, because sockseek refuses a key with an empty value (measured 2026-10-11:
`Error parsing config ... at line 0`). That is why the local file works as a general override,
not only as a place for the login:

```
username = your-soulseek-login
password = your-soulseek-password
min-bitrate = 320
```

`--sockseek-conf FILE` adds the top layer for one run - a second account, a lossless profile, a
machine-specific path - without touching either file on disk. A file that does not exist stops
the run with `ERROR: --sockseek-conf: no such file`.

Passing `--no-config` or your own `--config` through `--sockseek-args` switches the whole
mechanism off and leaves the config entirely to you (that is how the test suite runs sockseek
without a login).

What the script passes on the command line and must therefore not be set here: `output-dir`,
`length-tol`, `name-format`, `index-path`. Everything else left out of the file keeps sockseek's
own default: `search-timeout` (5 s), `max-retries`, `searches-per-time` (34) and
`searches-renew-time` (220 s), `concurrent-searches` (2), `strict-conditions`, `desperate`,
`artist-maybe-wrong`, `remove-brackets`, `remove-ft`.

One warning from experience: **`remove-brackets` only removes SQUARE brackets.** Playlist titles
like `Firework (Serafin Trance Edit)` use round ones, so the option does nothing for them.

## 8. Tracks not found

### Every failure explains itself

A failed track gets two kinds of line. First the raw codes from sockseek's index, with the code
spelled out, because reading it literally is a trap:

```
FAILED  state=2 reason=9 (no candidate passed the name/length/quality conditions)  You Got The Love (Club Calimari Remix) | 5:19
```

**`reason=9` does not mean "not on the network".** It means nothing passed the conditions. Run
#0004 found two 320 kbps copies of a track whose index row said 9 - they were rejected because
their length differed from the playlist by 27 s.

So after the run the script searches the failed tracks once more with **every condition off**
(one extra search per failed track) and says what is actually out there:

```
  -> nothing on the network: 0 candidates even with every condition off
  -> IS on the network: 2 candidate(s), closest 346s/320kbps
     rejected by length: playlist says 319s, diff +27s
     to take it: py run.py --only <playlist> --length-tol 28
  -> IS on the network: 1 candidate(s), closest 267s/320kbps
     length and quality are fine, so the uploader did not deliver - try again later,
     availability changes with who is online
```

Three different causes, three different things to do. `--no-explain` turns the extra search off
when the playlist is large and the search budget matters (section 6).

### Re-running the same playlist IS the workflow

There is no generated "missing" playlist any more. What is missing is computed every time from
the playlist and the index, so the next attempt is the same command on the same list:

```
py run.py --only my-playlist
```

It prints what is still missing, asks, and searches only those tracks. When nothing is missing,
sockseek is not started at all - not even to let it skip the files itself.

Why repeat at all: availability depends on who is online. A track that was nowhere on 2026-10-06
arrived on 2026-10-07 as flac 893 kbps, with no change to the tool. Run #0017 (2026-10-07 23:52)
is the honest picture of what is left after that: of 15 missing tracks, 12 had **no candidate at
all** even with every condition off, and 3 were found but their uploader never delivered. Nothing
in the code fixes either case; another hour of the day might.

A full run (no `--only`) takes every `.txt` in `Playlists/` that the tool did not generate
itself; the only generated files left are the sockseek list files in `work/`.
A run that leaves nothing missing deletes the stale file instead of lying about it.

**This is the workflow that actually gets more tracks.** Whether a track arrives depends on who
is online: on 2026-10-06 one track found nothing, and on 2026-10-07 the same search downloaded a
893 kbps flac, because its uploader had come back. Repeating only the missing lines a few days
later costs a handful of searches and needs no changes to anything.


First look at the `FAILED` lines in the run log (`logs/run_<NNNN>_<stamp>.log`). There is one
line per track that was not downloaded:

```
FAILED  state=2 reason=9  Funk Tribu - September - Cry For You (Funk Tribu Rework) | 5:37
```

`state` and `reason` are sockseek's `state` and `failurereason` codes from `_index.csv` (table
below); the rest is the matching line from your playlist, exactly as you wrote it. When a failed
index row cannot be matched to a playlist line reliably, the script says so instead of guessing:

```
FAILED  state=2 reason=9  (no matching playlist line, index title: Some Title)
```

A summary line names the run, so it can be found by number alone:

```
FAILED 16/30 track(s) in run #0043
```

A separate WARN is logged for failed index rows that match no line in this playlist at all
(for example rows left over from an older version of the playlist).

Rows come from the playlist's `_index.csv` (columns `filepath,artist,album,title,length,tracktype,state,failurereason`);
a row is a failure unless its state is 1 or 3. **Raw-code caveat**, all of it from observation,
none of it from documentation:

| `state` | Meaning | Confirmed how |
|---|---|---|
| `1` | downloaded during this run | real run 2026-10-06 and mock runs 2026-10-07 |
| `2` | failed (`failurereason=9` in every observed case) | real run 2026-10-06 and mock runs |
| `3` | already present, skipped — sockseek counts it as succeeded | three sequential mock runs 2026-10-07 |

Any other code is unconfirmed and is treated as a failure. What `failurereason=9` means is not
documented anywhere, so do not read more into it than "this one did not come down".

Index rows are **updated in place**, not appended: three runs over a two-track playlist left
exactly two data rows, and an already-downloaded track flips from `state=1` to `state=3` on the
next run. State 3 therefore has to count as success — otherwise every re-run would report every
previously downloaded track as a failure.

To force a track to download again, use sockseek's own `--no-skip-existing` (via
`--sockseek-args="--no-skip-existing"`) rather than hand-editing `_index.csv`.
The exit code of sockseek is **not** used to decide what failed.

Things to try, roughly in this order:

1. **Raise the length tolerance:** `--length-tol 6` (or `-1` to drop the length filter). The
   length filter is hard; a remix whose real length differs by 5 s is rejected at the default 3.
   This is the leading suspect for most "not found" tracks, but it is a hypothesis, not proven.
   (The filter only bites when the peer reports a length; see section 9.)
2. **`--artist-maybe-wrong`:** free-form SoundCloud titles often put the artist in the wrong place.
3. **`--remove-brackets`** and **`--remove-ft`:** drop `(Remix)`, `[FREE DOWNLOAD]`, `feat. ...`
   from the search text.
4. **`--sockseek-args="--desperate"`:** broader searching; slower and noisier.
5. **Do not use `--sockseek-args="--strict-conditions"`** unless you need it: it also rejects
   files whose metadata is merely unknown, which is most of the standard Soulseek client's shares.
   Rewriting the playlist line is pointless: runs #0004 and #0005 found the same files with and
   without the SoundCloud uploader prefix.
7. **`--preview`:** runs sockseek with `--print results`, so you see what the search actually
   returns for each line without downloading. Use it to decide whether the track exists on the
   network at all, or whether your search text is the problem.
8. For the detail on one run, add `--verbose` and read `logs/sockseek_<NNNN>_<name>.log`: it is
   the only place that distinguishes `No search results` (nothing passed the conditions) from
   `StaleDownloadException` (found, but the uploader sent nothing).

## 9. Length check (ffprobe) - off by default

**Off since 2026-10-07**, by the owner's call. Turn it on per run with `--ffprobe-check`:

```
py run.py --only my-playlist --ffprobe-check
```

While it is off, nothing verifies that a downloaded file holds the music that was asked for; the
only claim about a file is the one its uploader made.

With the flag, after a playlist finishes the script measures the files it downloaded and compares
each real duration with the length on the playlist line. **It only reports.** It never moves,
renames, quarantines or deletes a file, and it never changes the exit code, whatever it finds. It
does not run with `--dry-run` or `--preview`.

**What it measures.** For every `_index.csv` row whose state is 1 or 3 and whose `filepath` is
not empty, the file is resolved relative to the folder that holds that `_index.csv`, and each
file that exists is probed with:

```
ffprobe -v error -show_entries format=duration,bit_rate -of csv=p=0 <file>
```

Duration is rounded to whole seconds, the bit rate is reported in kbps. Each call has a 30 s
timeout, and anything that cannot be parsed is reported as unknown, not as an error. The playlist
line behind each file is found with the same matching as in section 8 and its length is compared
with the measured one:

- the line has a length and `length_tol_s >= 0`: the file is flagged when
  `abs(real - want) > length_tol_s`, using the same tolerance as the search filter;
- the line has no length, or `length_tol_s` is `-1`: the numbers are printed, the file is never
  flagged.

**What it logs.** One `CHECK` line per measured file, then one summary line (format examples):

```
CHECK  want=262 real=213 diff=-49 br=323kbps  MISMATCH  09. September - Cry For You (...).mp3
CHECK  want=277 real=277 diff=+0  br=2304kbps  Armin Hermann - We No Speak Americano (EDIT).wav
CHECK 1 of 14 file(s) outside +-3 s: 09. September - Cry For You (...).mp3
```

The bit rate is always printed because it is useful to know, but it never flags a file and is
never passed to sockseek (see below).

**Finding ffprobe.** `--ffprobe PATH` on the command line; without it, auto-detect: `ffprobe` on
`PATH`, then `C:\ffmpeg\bin\ffprobe.exe`. If none is found the script logs one WARN
(`ffprobe not found, skipping the length check, pass --ffprobe PATH`) and skips the step. A
missing ffprobe is a warning, not an error: the exit code is unchanged.

### Why the check exists: three verified facts

Established 2026-10-07 by measuring the owner's 14 downloaded files with `ffprobe`:

1. **The `length` column of `_index.csv` is the length from the playlist line, not a measured
   one.** Comparing it with the playlist gives a difference of 0 for every row by construction,
   so it proves nothing about the file on disk. Only ffprobe measures the real file.
2. **A file whose peer reports no length metadata bypasses `--length-tol` entirely.** Per
   `sockseek --help file-conditions`, sockseek "accepts common audio files with no length
   metadata", so when the uploader reports no length the hard length filter does not apply at
   all. Evidence: one of the 14 files is **49 s shorter** than its playlist line asked for (want
   262 s, real 213 s) and is a different edit of the track, yet it was accepted.
3. **`pref-min-bitrate` only ranks; it never rejects.** Evidence: four of the 14 files are below
   320 kbps, one of them at **83 kbps**.

All of the above was measured on 2026-10-07 with `ffprobe` over the 14 files from the 2026-10-06
run. At the shipped tolerance of 3 s exactly one file is flagged; at the tolerance of 1 s that run
actually used, two were outside the window (the second only by 2 s).

**No hard bitrate requirement, by the owner's decision.** The owner deliberately declined
`--min-bitrate`. sockseek's own help warns that `--strict-conditions` together with
`--min-bitrate` discards every share from standard Soulseek clients, because they do not
broadcast a bitrate. So the script never adds `--min-bitrate` to the sockseek command, and the
bit rate in the `CHECK` lines is information only.

## 10. Migrating old output

Older versions ran one process per track and left audio scattered in `output/<name>/NNN.list/`.
`tools/flatten_output.py` moves those files up into `output/<name>/`. It is a one-time tool:

```
py tools/flatten_output.py            rem dry run (default): only prints what would move
py tools/flatten_output.py --apply    rem really move
```

It only moves audio files, leaves every `_index.csv` where it is, and never overwrites an
existing file (it reports the clash and exits with `1`).

## 11. Tests

```
py -m unittest discover
py -m unittest discover -v
py -m unittest tests.test_importing      rem one component
```

213 tests, about 15 seconds.

One test module per component (`tests/test_playlist.py`, `test_runner.py`, `test_index.py`,
`test_settings.py`, `test_batch.py`, `test_explain.py`, `test_quality.py`, `test_importing.py`,
`test_ui.py`), with the shared fixtures in `tests/support.py`.

Tests that need sockseek use the real `sockseek.exe` with `--mock-files-dir` and `--no-config`:
no login, no network. They are skipped if `sockseek.exe` is missing. The ffprobe cases also need
`ffmpeg` and `ffprobe` (they generate files of a known duration) and are skipped without them.
**Never run sockseek against the real server from a test or experiment**; one stray run can earn
a 30-minute ban.
