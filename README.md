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

[Soulseek](https://www.slsknet.org) is a peer-to-peer network: people share folders from their
own machines, so a track is available only while the person who has it is online. This tool
drives [sockseek](https://github.com/fiso64/sockseek), a console Soulseek client, and adds the
part sockseek has no opinion about — what to ask for, what you already have, and what happened.

Python 3.10+, standard library only. Windows, macOS and Linux (measured on Windows).

**Written with AI.** Every line of this project — the code, the 275 tests and this documentation
— was written by an AI assistant (Claude), directed by the repository owner, with no second
human reviewer. The numbers below come from 34 numbered runs against the live network, whose
logs were kept; anything that could not be verified is named as such in
[the manual](docs/README.md).

---

## Quick start

```bash
git clone https://github.com/litetook/sockseek-cli-playlist-downloader
cd sockseek-cli-playlist-downloader
py setup.py          # downloads sockseek at the pinned version, sha256 verified
py run.py            # creates the config files and asks for your Soulseek login
```

Three things to do once:

1. **Python 3.10+** — `py --version` on Windows, `python3 --version` elsewhere. If it is not
   there: [python.org/downloads](https://www.python.org/downloads/), and on Windows tick
   *Add python.exe to PATH* in the installer.
2. **A Soulseek login.** The first run creates `sockseek.local.conf` and stops:

   ```
   Put your Soulseek login in ...\sockseek.local.conf:
       username = your-login
       password = your-password
   Then run this again.
   ```

   The file is git-ignored and nothing in the logs prints its values.
3. **A playlist** — a `.txt` file in `Playlists/`, one track per line
   (`Playlists/example.txt` is there to copy):

   ```
   Daft Punk - Around the World | 7:09
   Fatboy Slim - Praise You | 5:23
   ```

   The part after `|` is the length (`m:ss`, `h:mm:ss` or seconds). It is what keeps another
   version of the same song out, so a line without it searches without that filter. Lists
   exported from other programs can be converted — see [Importing a list](#importing-a-list).

Then run it:

```bash
run.cmd              # Windows
./run.sh             # macOS, Linux
py run.py            # same thing, calling Python yourself
```

Downloads land flat in `output/<playlist>/`, named `Artist - Title.ext`.

---

## Workflow

The tool is built around running the same list again, because one pass is never the whole story:
a track that was nowhere on 2026-10-06 arrived on 2026-10-07 as a 893 kbps flac, with nothing
changed in the code. On a fresh 10-track list the first run brought 6, a run 30 seconds later
brought 2 more, a third brought the last 2.

```bash
py run.py                              # pick a playlist, see what is missing, confirm
py run.py --only my-playlist           # skip the menu
py run.py --only my-playlist --yes     # skip the confirmation too
```

Every run:

1. Works out what is already on disk — from sockseek's index **and** the files themselves.
2. Searches **only** the missing tracks. The rest are not sent to sockseek at all; when nothing
   is missing, sockseek is not started.
3. Reports every track that arrived, and for every one that did not, why.

A file already on disk is never downloaded again, and nothing that was downloaded is ever
overwritten or deleted.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | the run worked. Tracks may still be missing — that is Soulseek, not a bug |
| `1` | the tool failed: sockseek could not start, was killed by the timeout, or exited with an error and wrote no index |
| `2` | setup problem: no login yet, no sockseek, an unknown playlist name, a config file that does not exist |
| `130` | Ctrl+C |

A non-zero exit from sockseek alone is not a failure: it returns one whenever a single track
fails, which is the everyday case.

---

## Configuration

Three files. Each one is created from a built-in template when it is missing, so deleting a file
brings back the documented values instead of losing them quietly.

| File | Holds | Read by |
|---|---|---|
| `config.yaml` | the folders, and three numbers for the search | this tool |
| `sockseek.conf` | quality, waiting, search behaviour | sockseek |
| `sockseek.local.conf` | your Soulseek login, plus any key you want changed on this machine | both |

`sockseek.local.conf` is the only one that holds secrets: nothing in the logs prints its values,
and it is git-ignored.

### `config.yaml`

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

| Key | Flag | Default | What it means |
|---|---|---|---|
| `paths.sockseek` | `--sockseek` | `sockseek.exe` | The sockseek binary. `sockseek` without `.exe` is accepted too, so one file works on Windows and macOS |
| `paths.playlists` | `--playlists` | `Playlists` | Folder scanned for playlist `.txt` files |
| `paths.output` | `--output` | `output` | Where `<playlist>/` folders with the audio and the index go |
| `search.length_tol_s` | `--length-tol` | `45` | Seconds around the length on the playlist line, a **hard** condition; `-1` turns it off. 45 because playlist lengths run shorter than the copies people share: 319 s in the list against 346 s on the network, same remix |
| `search.retries` | `--retries` | `1` | Attempts per playlist. A retry searches only what is still missing, and doubles the wall clock |
| `search.playlist_timeout_min` | `--playlist-timeout` | `10` | Minutes for one attempt at one playlist, after which the process is killed. `0` = no limit |

A relative path is relative to the folder holding `run.py`; an absolute one is taken as it is.
The command line wins over the file, and every run log opens with the values in force and where
each came from (`cli`, `config`, `default`).

The file is read as flat `key: value` pairs, so section names are decoration. A line that is not
a pair, a value below the legal minimum and an unknown key are each named in a `WARN` line and
then ignored. A key missing from the file falls back to a built-in value, which for two of them
is not the one above: `retries` 2 and `playlist_timeout_min` 40.

### `sockseek.conf`

sockseek's own option names without the leading `--`, and its own units; `sockseek.exe --help`
is the full list. `min-bitrate` is the only hard condition here — every `pref-` key merely ranks
candidates, and one that fails it is still accepted.

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

| Key | Default | What it means |
|---|---|---|
| `min-bitrate` | `256` | Hard floor in kbps. A file whose uploader reports no bitrate at all is still accepted - the standard Soulseek client reports none |
| `max-bitrate` | *not set* | Deliberately absent: no upper limit. Add `max-bitrate = N` if you want one |
| `pref-min-bitrate` | `320` | Prefer 320 kbps and above |
| `pref-max-bitrate` | `1000000` | Lifts sockseek's own cap of 2500, which ranked 24-bit lossless below an mp3 320 |
| `pref-format` | `flac,wav,mp3` | Prefer these formats. The list is unordered: flac is not preferred over mp3 by being written first |
| `max-stale-time` | `30000` | Milliseconds without transfer activity before a candidate is dropped and the next one tried. This is sockseek's own default: a 5-minute window was tried and measured at 25 minutes on 15 tracks with nothing downloaded |
| `fast-search` | `true` | Take a file as soon as one passes the preferred conditions, instead of letting the search run out (`search-timeout`, 5 s) and then picking the best of everything that answered |
| `fast-search-delay` | `2000` | Milliseconds in which answers are only collected and nobody may be taken yet. sockseek's own 300 amounts to "whoever answered first", because answers keep arriving for seconds; 2 s leaves something to choose from |
| `fast-search-min-up-speed` | `200` | The speed an uploader must report to be taken **early**. It gates that shortcut only - a slower one stays in the normal set and can still be chosen when the search finishes - so no track is lost to it. sockseek's own `1` accepts anybody; the unit is undocumented |
| `pref-strict-title`, `pref-strict-artist` | `true` | Prefer candidates whose path contains the title / the artist |

**Not set here, and should not be:** `output-dir`, `length-tol`, `name-format` and `index-path`
are passed on the command line on every run, so a value in the file would be dead.
`strict-conditions` would turn every `pref-` check into a hard one and discard every share from
the standard Soulseek client, which reports no bitrate.

**Left at sockseek's own defaults:** `search-timeout` (5 s), `searches-per-time` (34) and
`searches-renew-time` (220 s) - the limiter that keeps the account out of the server's 30-minute
ban - `concurrent-searches` (2), `max-retries`, `desperate`, `artist-maybe-wrong`,
`remove-brackets`, `remove-ft`. A `[profile]` section works as sockseek documents it.

### `sockseek.local.conf`

```
username = your-login
password = your-password
```

Your Soulseek account: without it a run stops with a message and starts nothing. Any other key
of `sockseek.conf` can be repeated here to change it on this machine only.

### Layers

sockseek reads one config file and has no `include`, so the layers are merged into
`work/sockseek.effective.conf`, and that merged file is what sockseek is given:

```
sockseek.conf                   the defaults that come with the tool
  └─ sockseek.local.conf        your login, and anything you change on this machine
       └─ --sockseek-conf FILE  this run only
```

Each layer may hold as few keys as it likes. A key replaces the same key of a lower layer, a new
key is added above any `[profile]` section, and the profiles themselves are copied untouched.

```bash
py run.py --only my-playlist --sockseek-conf lossless.conf
```

### `dependencies.yaml`

The external tools and their pinned versions. `py setup.py --upgrade` rewrites the versions and
checksums from the newest releases; which asset belongs to which platform stays as written.

| Key | What it means |
|---|---|
| `<tool>.version` | The release to install, substituted into the url and the asset name |
| `<tool>.url` | Download template, with `{version}` and `{asset}` |
| `<tool>.optional` | `true` means `setup.py` skips it unless `--all`; it is still fetched on demand if something needs it |
| `<tool>.<platform>.asset` | File name in that release, per `windows`, `macos-arm64`, `macos-x64`, `linux-x64`, `linux-arm` |
| `<tool>.<platform>.sha256` | Checksum, verified before the file is put in place |
| `<tool>.<platform>.member` | The file to take out of an archive; absent means the download is the binary itself |
| `python.packages` | Pinned `name==version` entries, comma separated, installed into `vendor/`. Empty: this tool uses the standard library only |

---

## Options

```
py run.py --only <name> --length-tol 90                 a wider length window, once
py run.py --only <name> --no-explain                    skip the extra search per failure
py run.py --only <name> --preview                       print the search results, download nothing
py run.py --only <name> --dry-run                       print the sockseek command, run nothing
py run.py --only <name> --verbose                       keep sockseek's own log in logs/
py run.py --only <name> --ffprobe-check                 measure the files, report mismatches
py run.py --only <name> --sockseek-args="--desperate"   pass anything through to sockseek
py run.py --version
py run.py --help                                        and py -m soulseek --help for the engine
```

`--ffprobe-check` is off by default: the contents of a downloaded file are not inspected unless
asked. ffprobe is not one of the pinned tools, so it has to be on `PATH` (part of ffmpeg) or
named with `--ffprobe PATH`.

### Dependencies

```bash
py setup.py            install what is missing
py setup.py --check    what is installed, and which versions
py setup.py --upgrade  re-pin dependencies.yaml to the newest releases
py setup.py --all      include the optional tools
```

The pins live in [`dependencies.yaml`](dependencies.yaml) — a version and a sha256 per
platform, verified before anything is put in place, key by key in
[Configuration](#dependenciesyaml). Nothing is installed system-wide.

| Tool | Pinned | For |
|---|---|---|
| [sockseek](https://github.com/fiso64/sockseek) | 3.0.5 | searching and downloading |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 2026.08.19 | not used yet — pinned for reading playlist links, skipped unless `--all` |

Running setup is optional: a run that needs a tool it cannot find offers to fetch that one,
after the playlist is chosen and the download confirmed.

---

## Importing a list

A playlist file is the tool's own interface, and `--import` fills one in - from a file another
program exported, or from a link. Either way it only writes the file and stops: the downloading
is the separate, confirmed step, so an import never costs you anything.

```bash
py run.py --import "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
py run.py --import "https://soundcloud.com/bonobo/sets/outlier-radio-on-nts"
py run.py --import "C:\exports\my set.m3u8"
py run.py --import tracks.csv --as techno-2026 --overwrite
```

### From a link

| Service | What it needs | Limit |
|---|---|---|
| Spotify playlist or album | nothing - no account, no API key, no developer application, no Premium | the page it reads gives **at most 100 tracks**, and the playlist must be public |
| SoundCloud set | `yt-dlp`, offered for download the moment you pass such a link | a private set needs `--cookies-from-browser chrome` (you are logged in there, not here) |

The playlist's own name becomes the file name (`Today's Top Hits` -> `todays-top-hits.txt`), or
pass `--as`. When Spotify returns exactly 100 tracks the import says so, because a longer
playlist is cut there and nothing else would tell you.

Spotify is read from its embed page, which carries the track list as JSON; SoundCloud has no
such page, and sockseek has no SoundCloud input either, so `yt-dlp` reads that one. Beatport is
not supported: it is partner-gated and blocks automated browsers.

### From a file

| Format | Where the length comes from |
|---|---|
| `.m3u`, `.m3u8` | `#EXTINF:249,Artist - Title`, in seconds (`-1` = unknown) |
| `.csv`, `.tsv` with a header | a duration column: `Duration (ms)`, `duration`, `time`, `length` |
| any other text | one name per line, no lengths |

The title column is looked up among `Track Name`, `title`, `name`, `track`, `song`; the artist
among `Artist Name(s)`, `artist`, `artists`, `album artist`. Anything skipped is named in a
`WARN` line. An existing playlist is not replaced without `--overwrite`.

---

## How it works

```
run.py            you  ←  menu, status, "download these 4?"
  └─ cli.py       command line + config.yaml
      └─ batch.py the run: playlist by playlist, the log, the exit code
           ├─ playlist.py   text line  ->  Entry (name + length)
           ├─ index.py      what is already here, and what failed
           ├─ runner.py     the sockseek command and the process around it
           ├─ explain.py    why a track did not arrive
           ├─ quality.py    optional ffprobe report
           ├─ links.py      a playlist link read without an account
           └─ deps.py       the pinned tools: resolve, download, verify, install
settings.py       config.yaml and sockseek.conf
importing.py      m3u / csv / plain text  ->  a playlist file
links.py          a Spotify or SoundCloud link  ->  a playlist file
```

**1. Read the list.** `Daft Punk - Around the World | 7:09` becomes a search string and a length
of 429 seconds. The name is kept whole, never split into artist and title: a line is free-form
(`Nova Blue - Kate Ryan - Song (Remix)` puts the uploader first, not the artist) and the search
returns the same files either way.

**2. See what is already here.** Every line is matched against sockseek's `_index.csv`, and a
track counts as present only when both hold: the index says it arrived *and* the file is on disk.
Delete a file and it shows up as missing again. File names alone cannot be used for this — they
come from the uploader (`... (Clean) 1A 142 [www.dj-promo.org].mp3`).

**3. Ask.** The missing tracks are printed, numbered, before a single search happens.

**4. Search and download.** Only the missing lines are written to `work/<playlist>.list.txt` and
handed to one sockseek process. One process matters: sockseek has a single search limiter
(34 searches per 220 s) that keeps the account out of the server's 30-minute ban. When the
limiter is reached, tracks show as `Waiting` — queued, not stuck.

**5. Report.** The status is computed again, and the difference is the answer:

```
OK      Moby - Porcelain | 4:01
FAILED  state=2 reason=4 (found, but the download did not come through)  Massive Attack - Teardrop | 5:29
  -> IS on the network: 218 candidate(s), closest 330s/813kbps
     length and quality are fine, so the uploader did not deliver - try again later
run #0029: 2 arrived, 2 still missing, 8 of 10 in the folder
```

`reason=9` is worth knowing: sockseek prints it as *no search results*, but it means nothing
passed the conditions. That is why a second, conditionless search runs for every failure and
says which of three things happened — nothing is shared, our conditions rejected it, or the
uploader did not deliver.

---

## Project layout

```
run.py                 the one command: menu, status, confirmation, --import
run.cmd / run.sh       launchers for Windows and macOS/Linux
setup.py               installs the pinned tools
soulseek/              the engine, one module per component
tests/                 one test module per component
config.yaml            this tool's settings
sockseek.conf          sockseek's options, no secrets
sockseek.local.conf    your login and any override (git-ignored)
dependencies.yaml      pinned versions and checksums
Playlists/             your lists, one .txt per playlist
output/<playlist>/     the audio, flat, plus sockseek's _index.csv
work/                  generated list files and the merged sockseek config
logs/                  run_<NNNN>_<time>.log per run
docs/README.md         the manual: every option, every trap, with evidence
```

## Tests

```bash
py -m unittest discover
py -m unittest tests.test_importing      # one component
```

275 tests, about 15 seconds, no network. The ones that need sockseek use the real binary in
`--mock-files-dir` mode and skip themselves if it is absent; the ffprobe ones skip without
ffmpeg. Never point a test at the real server — one stray run can earn a 30-minute ban.

## Limitations

- It does not replace a file you already have with a better copy.
- It does not rank uploaders by speed: sockseek cannot, and this tool does not pick candidates
  itself.
- It cannot fix a track nobody shares. On a playlist of SoundCloud edits, 12 of 15 leftovers had
  no candidate at all with every condition off.
- macOS and Linux are supported but untested.

## License

MIT — see [LICENSE](LICENSE). Not affiliated with Soulseek or sockseek.
