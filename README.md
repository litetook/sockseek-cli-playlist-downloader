# sockseek CLI playlist downloader

Give it a list of tracks. It tells you which ones you already have, which ones are missing, and
downloads only the missing ones from Soulseek — after you say yes.

```
Playlists:

  #  playlist                      tracks  here  missing
  -  ----------------------------  ------  ----  -------
  1  classics-test                     10     6        4
  2  melodic-ambient-playlist          25    25        0

What to download? (1, or 1,2, or all; Enter quits): 1

classics-test: 10 tracks, 6 here, 4 missing

Missing:
   1  The Chemical Brothers - Hey Boy Hey Girl | 4:46
   2  Moby - Porcelain | 4:01
   3  Air - La Femme d'Argent | 7:11
   4  Massive Attack - Teardrop | 5:29

Download these 4? [y] yes  [n] no: y
```

Python 3.10+, standard library only — nothing to `pip install`. Developed and measured on
Windows; macOS and Linux should work but are untested (see [Install](#install)). It drives
[sockseek](https://github.com/fiso64/sockseek) — a console Soulseek client — and adds the part
sockseek has no opinion about: what to ask for, what you already have, and what happened.

---

## Why it exists

A playlist of 30 tracks is a boring, repetitive job: search each name, check it is the right
version, check the quality, keep track of what failed, come back later for the rest. The
official Soulseek client is a window with a mouse — it cannot take a list.

And the coming-back-later part is not optional. **Soulseek is other people's computers.** A
file exists for you only while the person sharing it is online, so the same list gives different
results at different hours. Measured on this repo's own runs: a track that was nowhere on the 6th
arrived on the 7th as a 893 kbps flac, with nothing changed in the code. On a fresh 10-track list
the first run brought 6, a run 30 seconds later brought 2 more, a third brought the last 2.

So the tool is built around repetition rather than around clever searching:

| The job | How it is handled |
|---|---|
| What do I already have? | Decided before anything else, from sockseek's index **and** the files on disk |
| What should be searched? | Only what is missing — the rest is not even sent to sockseek |
| Did I get the right version? | A length window, plus the fact that Soulseek requires every word of the query in the file path |
| Why did this one fail? | One extra conditionless search per failure, which separates "nobody shares it" from "our conditions rejected it" from "the uploader did not deliver" |
| Can I just run it again? | That is the normal workflow. Same command, same list — it searches only the leftovers |

Nothing is ever overwritten or deleted. A file already on disk is never re-downloaded.

---

## Install

### 1. Python 3.10 or newer

Check what you have — if either command prints a version, you are done:

```
py --version        (Windows)
python3 --version   (macOS, Linux)
```

If not:

| | Download | Official instructions |
|---|---|---|
| **Windows** | [python.org/downloads/windows](https://www.python.org/downloads/windows/) | [Using Python on Windows](https://docs.python.org/3/using/windows.html) — in the installer **tick "Add python.exe to PATH"**, that is the step people skip |
| **macOS** | [python.org/downloads/macos](https://www.python.org/downloads/macos/) | [Using Python on macOS](https://docs.python.org/3/using/mac.html) — or `brew install python` if you have [Homebrew](https://brew.sh) |

The Python shipped with macOS may be old; the installer above puts a current one in
`/usr/local/bin/python3` and does not touch the system one. Nothing else to install: this tool
uses the standard library only.

### 2. The external tools — one command

```
py setup.py
```

That downloads the tools this one drives, at the versions pinned in
[`dependencies.yaml`](dependencies.yaml), verifies the **sha256 of every file before it is put
in place**, and leaves them next to `run.py`. Nothing is installed system-wide, nothing needs
administrator rights.

| Tool | Pinned | What for |
|---|---|---|
| [sockseek](https://github.com/fiso64/sockseek) | 3.0.5 | the Soulseek client: searching and downloading (~50 MB) |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 2026.08.19 | **not used yet** — pinned for reading SoundCloud playlists, which is not implemented; `setup.py` skips it unless you ask for `--all` (~17 MB) |

```
py setup.py --check      what is installed, and which versions
py setup.py --upgrade    re-pin dependencies.yaml to the newest releases, then install
```

**Running it is optional.** A run that needs a tool it cannot find offers to fetch exactly that
one — after you have chosen a playlist and confirmed the download, never before:

```
Download these 3? [y] yes  [n] no: y
sockseek is not at …\sockseek.exe
sockseek 3.0.5 is missing. Download it? [y] yes  [n] no:
```

So it makes no difference whether you ran setup first. Already have the binaries? Then nothing
is downloaded and nothing changes.

On macOS the tools are made executable automatically; the first launch may still need
**System Settings → Privacy & Security → Open Anyway**, because they are not notarised by Apple.

> A macOS build of sockseek exists, but this tool has **not been run on macOS yet**: it was
> developed and measured on Windows. The Python side has nothing Windows-specific in it, so it
> should work — if you try it, the first run is the test.

### 3. Your Soulseek login

The first run creates the three files it needs and then stops, because nothing can be downloaded
until it knows who you are:

```
py run.py
  WARN created config.yaml from the built-in template
  WARN created sockseek.conf from the built-in template
  WARN created sockseek.local.conf: put your Soulseek login there

  Put your Soulseek login in …\sockseek.local.conf:
      username = your-soulseek-login
      password = your-soulseek-password
  Then run this again. Nothing can be downloaded until then.
```

Fill those two lines in and run it again. That file is git-ignored, it is the only file that
holds secrets, and nothing in the logs ever prints its values. See
[Configuration](#configuration) — the same file can override any other setting, and you can
point at a different one per run.

`config.yaml` and `sockseek.conf` are in the repository already; they are only written from the
built-in templates when they are missing, so deleting one gets the documented values back
instead of silently losing them.

### 4. A playlist

A `.txt` file in `Playlists/`, one track per line (`Playlists/example.txt` is there to copy):

```
Daft Punk - Around the World | 7:09
Fatboy Slim - Praise You | 5:23
```

The part after `|` is the length (`m:ss`, `h:mm:ss` or plain seconds). You can also generate the
file from an export — see [Importing a list](#importing-a-list).

### 5. Run it

```
run.cmd                 Windows: double-click it, or run it from a terminal
./run.sh                macOS / Linux
py run.py               the same thing, if you prefer calling Python yourself
py run.py --version     which version this is
```

Both scripts only find Python and hand over to `run.py`; they take the same options. Skip the
menu with `--only my-playlist`, and the confirmation too with `--yes`.

Downloads land flat in `output/<playlist>/`, named `Artist - Title.ext`.

---

## How it works

```
run.py            you  ←  menu, status, "download these 4?"        starts nothing by itself
  └─ cli.py       command line + config.yaml
      └─ batch.py the run: playlist by playlist, the log, the exit code
           ├─ playlist.py   text line  ->  Entry (name + length)
           ├─ index.py      WHAT IS ALREADY HERE, and what failed
           ├─ runner.py     the sockseek command and the process around it
           ├─ explain.py    why a track did not arrive
           └─ quality.py    optional ffprobe report
settings.py       two config files: this tool's config.yaml and sockseek.conf
importing.py      m3u / csv / plain text  ->  a playlist file
```

One playlist, step by step:

**1. Read the list.** `Daft Punk - Around the World | 7:09` becomes a search string and a length
of 429 seconds. The name is kept whole — never split into artist and title, because a line is
free-form (`Nova Blue - Kate Ryan - Song (Remix)` puts the uploader first, not the artist) and
splitting it is a guess. Measured: the search finds the same files either way.

**2. See what is already here.** For every line, sockseek's `_index.csv` is matched against the
playlist, and a track counts as present only when **both** hold: the index says it arrived *and*
the file is really on disk. Delete a file and it shows up as missing again. File names alone
cannot be used for this — they come from the uploader
(`... (Clean) 1A 142 [www.dj-promo.org].mp3`) and no longer carry the playlist line.

**3. Ask.** The missing tracks are printed, numbered, before a single search happens.

**4. Search and download.** Only the missing lines are written to `work/<playlist>.list.txt` and
handed to **one** sockseek process. One process matters: sockseek has a single search limiter
(34 searches per 220 s) that keeps the account out of the server's 30-minute ban, and several
processes would defeat it.

**5. Report.** The status is computed again, and the difference is the answer:

```
OK      Moby - Porcelain | 4:01
FAILED  state=2 reason=4 (found, but the download did not come through)  Massive Attack - Teardrop | 5:29
  -> IS on the network: 218 candidate(s), closest 330s/813kbps
     length and quality are fine, so the uploader did not deliver - try again later
run #0029: 2 arrived, 2 still missing, 8 of 10 in the folder
```

`reason=9` is worth knowing: sockseek prints it as *no search results*, but it means **nothing
passed the conditions**, not that the track is absent. That is exactly why the extra
conditionless search exists.

**Exit codes:** `0` — the run worked (tracks may still be missing, that is Soulseek, not a bug);
`1` — the tool itself failed; `2` — setup problem (no login, no sockseek, unknown playlist name);
`130` — Ctrl+C.

---

## Configuration

Two files, and the split is deliberate: **this tool's own settings** versus **sockseek's**.

### `config.yaml` — the folders and three numbers

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

A relative path is relative to the folder holding `run.py`; an absolute one (`output: D:\music`)
is taken as it is. Command line beats the file, and every run log starts with the effective
values and where each came from (`cli`, `config`, `default`).

- `length_tol_s` — the length window in seconds, a **hard** condition; `-1` turns it off.
  45 because playlist lengths run systematically shorter than the copies people share (measured:
  319 s in the list, 346 s on the network, same remix).
- `retries` — attempts per playlist. More than one doubles the wall clock for little gain.
- `playlist_timeout_min` — wall clock per attempt; a real 30-track run takes about 6 minutes.

### `sockseek.conf` — quality, waiting, search behaviour

```
min-bitrate = 256
pref-min-bitrate = 320
pref-max-bitrate = 1000000
pref-format = flac,wav,mp3

max-stale-time = 30000
fast-search = true
fast-search-delay = 2000
fast-search-min-up-speed = 200
pref-strict-title = true
pref-strict-artist = true
```

- `min-bitrate` is the only hard floor. There is **no** maximum — unlimited on purpose; add
  `max-bitrate = N` if you want one.
- `pref-max-bitrate = 1000000` exists to lift sockseek's own default ranking cap of 2500 kbps,
  which quietly ranked 24-bit lossless *below* an mp3 320.
- `max-stale-time` — milliseconds without transfer activity before an uploader is dropped.
  30 s. A 5-minute window was tried and measured: it cost 25 minutes on 15 tracks and brought
  nothing, because those uploaders do not deliver at all rather than slowly.
- `fast-search-min-up-speed` — a pass mark for the uploader's reported speed, meant to skip the
  ones that never deliver. Set it to `1` to switch it off.
- `pref-*` keys only **rank**; they never reject.

Do not set `strict-conditions`: together with `min-bitrate` it discards every share from the
standard Soulseek client, which does not broadcast a bitrate at all.

### Layers: the same file, overridden

sockseek reads exactly **one** config file and has no `include`, so this tool merges the layers
itself into `work/sockseek.effective.conf` and points sockseek at that file:

```
sockseek.conf          published defaults, no login
  └─ sockseek.local.conf        this machine: your login and anything you want changed
       └─ --sockseek-conf FILE  this run only
```

Every layer has the same syntax and **may hold as few keys as it likes** — one key is fine. A key
replaces the same key of a lower layer, a new key is added, and a `[profile]` section is copied
untouched. The published `sockseek.conf` keeps `username` and `password` visible but commented
out, because sockseek refuses a key with an empty value (measured: `Error parsing config ... at
line 0`).

```
# sockseek.local.conf — your machine, git-ignored
username = your-soulseek-login
password = your-soulseek-password
min-bitrate = 320
```

```
# lossless.conf — one run, one key
py run.py --only my-playlist --sockseek-conf lossless.conf
```

```
pref-format = flac,wav
```

Handy for a second account, a different quality profile, or a machine-specific path — and it is
the easy thing for a setup script to write, since it never has to touch the published file.
Without a login in any layer the run stops with a message naming the file to fill in.

---

## Importing a list

```
py run.py --import "C:\exports\my set.m3u8"
py run.py --import tracks.csv --as techno-2026
py run.py --import tracks.csv --as techno-2026 --overwrite
```

| Format | Where the length comes from |
|---|---|
| `.m3u`, `.m3u8` | `#EXTINF:249,Artist - Title`, in seconds (`-1` = unknown) |
| `.csv`, `.tsv` with a header | a duration column: `Duration (ms)`, `duration`, `time`, `length` |
| any other text | one name per line, no lengths |

The title column is looked up among `Track Name`, `title`, `name`, `track`, `song`; the artist
among `Artist Name(s)`, `artist`, `artists`, `album artist`. Anything skipped is named in a
`WARN` line. An existing playlist is never replaced without `--overwrite`.

A length is only used for filtering: a line without one still works, just without that
protection. Importing from a **link** (Spotify, SoundCloud, Beatport) is not implemented — it
would be a separate input in front of this one.

---

## Other options

```
py run.py --only <name> --length-tol 90     a wider length window, once
py run.py --only <name> --no-explain        skip the extra search per failure
py run.py --only <name> --preview           print what the search returns, download nothing
py run.py --only <name> --dry-run           print the sockseek command, run nothing
py run.py --only <name> --verbose           keep sockseek's own log in logs/
py run.py --only <name> --ffprobe-check     measure the downloaded files and report mismatches
py run.py --only <name> --sockseek-conf other.conf          one more config layer, this run
py run.py --only <name> --sockseek-args="--desperate"      pass anything through to sockseek
py -m soulseek.cli --help                   every engine option
```

`--ffprobe-check` is off by default: the tool does not inspect the contents of what you
downloaded unless you ask. With it, every file is measured with ffprobe and a length or bitrate
mismatch is reported — a report only, nothing on disk is touched.

---

## Where things are

```
run.cmd / run.sh       launchers for Windows and macOS/Linux
setup.py               installs the pinned external tools
dependencies.yaml      the pins: version + sha256 per platform, per tool
Playlists/            your lists, one .txt per playlist
output/<playlist>/     the audio, flat, plus sockseek's _index.csv
work/                  generated list files and the merged sockseek config
logs/                  run_<NNNN>_<time>.log per run, run_seq.txt holds the last number
soulseek/              the engine, one module per component
tests/                 one test module per component
docs/README.md         the detailed manual: every option, every trap, with evidence
```

## Tests

```
py -m unittest discover
```

238 tests, about 15 seconds, no network. The ones that need sockseek use the real binary in
`--mock-files-dir` mode (no login, no network) and skip themselves if it is absent; the ffprobe
ones skip without ffmpeg. **Never point a test at the real server** — one stray run can earn a
30-minute ban.

## What it does not do

- It does not replace a file you already have with a better copy. Quality upgrades are not
  implemented, because that is the only operation here that could lose a file.
- It does not rank uploaders by speed — sockseek cannot, and the tool does not pick candidates
  itself.
- It does not fix a track nobody shares. On a playlist of SoundCloud edits, most failures are
  exactly that: 12 of 15 leftovers had no candidate at all, with every condition off.
- It does not touch Soulseek's rules. Share something back; the network runs on people leaving
  their client open.

---

Not affiliated with Soulseek or sockseek. Use it for music you are allowed to have.
