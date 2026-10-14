"""Turning a playlist link into playlist lines.

Two services, two mechanisms, neither of which asks the user to register anything:

    Spotify     the embed page carries the whole track list as JSON - title, artist and the
                length in milliseconds. No login, no API key, no developer application and no
                Premium. Its ceiling is 100 tracks (measured 2026-10-12: two different long
                playlists both stopped at exactly 100), and a playlist that is not public is
                not there at all.
    SoundCloud  sockseek has no SoundCloud input type, so yt-dlp reads it. A public set needs
                nothing; a private one needs the browser's own cookies, which is what
                `cookies_from` passes to `--cookies-from-browser`.

A link only ever becomes a playlist file. The downloading stays with the engine, so a link
goes through the same "this is what is missing, confirm it" workflow as a hand-written list -
and the file stays readable and editable afterwards.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

from .importing import track_line

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/140.0 Safari/537.36")
FETCH_TIMEOUT_S = 25
YTDLP_TIMEOUT_S = 300

EMBED_MAX = 100          # the embed page's own ceiling, not ours
SPOTIFY_EMBED = "https://open.spotify.com/embed/{kind}/{id}"
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
ENTITY_PATH = ("props", "pageProps", "state", "data", "entity")
SPOTIFY_REF = re.compile(r"(?:open\.spotify\.com/(?:intl-[\w-]+/)?(?P<kind>playlist|album)/"
                         r"|spotify:(?P<kind2>playlist|album):)(?P<id>[A-Za-z0-9]+)")

# a separator no track title carries, so yt-dlp's one line per track can be split safely
FIELD_SEP = "\x1f"
YTDLP_FIELDS = FIELD_SEP.join(("%(playlist_title)s", "%(title)s", "%(uploader)s",
                               "%(duration)s"))
UNKNOWN = ("", "na", "none", "null")


class LinkError(Exception):
    """A link that cannot be read, with a message meant for the person who passed it."""


@dataclass(frozen=True)
class Linked:
    """What one link produced. `name` is the playlist's name at the source, for the file name."""
    lines: list[str]
    warnings: list[str]
    source: str                 # "spotify" or "soundcloud"
    name: str = ""

    def text(self) -> str:
        return "\n".join(self.lines) + "\n" if self.lines else ""


def is_link(text: str) -> bool:
    """Whether `--import` was given a link rather than a file. An http link to a service we
    cannot read is still a link: it deserves "I cannot read this one", not "no such file"."""
    text = str(text).strip().lower()
    return text.startswith(("http://", "https://", "spotify:"))


def detect(text: str) -> Optional[str]:
    """"spotify", "soundcloud", or None for a link to something we cannot read."""
    text = str(text).strip()
    if text.lower().startswith("spotify:"):
        return "spotify"
    if not is_link(text):
        return None
    host = urlsplit(text).netloc.lower().split("@")[-1].split(":")[0]
    if host == "spotify.com" or host.endswith(".spotify.com"):
        return "spotify"
    if host == "soundcloud.com" or host.endswith(".soundcloud.com"):
        return "soundcloud"
    return None


def slug(name: str) -> str:
    """A playlist name turned into a file name: `Lo-Fi Beats (2024)` -> `lo-fi-beats-2024`."""
    # an apostrophe is dropped, not turned into a separator: "Today's" -> "todays", not "today-s"
    cleaned = re.sub(r"['’ʼ`]", "", str(name))
    cleaned = re.sub(r"[^\w\s-]", " ", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"[\s_]+", "-", cleaned.strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-").lower()
    return cleaned


def _fetch(url: str) -> str:
    import urllib.request                      # local: nothing imports the network by accident
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as response:
        return response.read().decode("utf-8", "replace")


def ytdlp_env() -> dict:
    """The environment yt-dlp is given, with its output forced to UTF-8.

    yt-dlp is a Python program, and on Windows a Python child writes its output in the console
    code page, not UTF-8. We read that output as UTF-8, so every character the code page cannot
    represent arrived as U+FFFD - measured 2026-10-14 on a real import, which wrote
    `RAW - RAWCAST148 � ALIS.` into a playlist. That is not cosmetic: the line goes
    straight into the search, and Soulseek wants every word of the query to appear in the file
    path, so such a track can never be found.
    """
    return {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _run(args: list[str]) -> tuple[int, str]:
    done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=YTDLP_TIMEOUT_S, env=ytdlp_env())
    return done.returncode, done.stdout or ""


def _seconds(text: str) -> Optional[int]:
    """yt-dlp prints `249.03` or `NA`; Spotify gives milliseconds as a number."""
    text = (text or "").strip()
    if text.lower() in UNKNOWN:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return int(value + 0.5) if value > 0 else None


class LinkReader:
    """Reads a playlist link. `fetch` and `run` are injected so the tests never touch the
    network: the fragile part is someone else's page, not our parsing."""

    def __init__(self, fetch: Optional[Callable[[str], str]] = None,
                 run: Optional[Callable[[list[str]], tuple[int, str]]] = None) -> None:
        self.fetch = fetch or _fetch
        self.run = run or _run

    def read(self, url: str, tool: Optional[Path] = None,
             cookies_from: Optional[str] = None) -> Linked:
        """The one entry point. Never raises for a link we simply could not read: the reason
        comes back as a warning, so the caller reports it like any other import problem."""
        kind = detect(url)
        try:
            if kind == "spotify":
                return self.spotify(url)
            if kind == "soundcloud":
                return self.soundcloud(url, tool, cookies_from)
            return Linked([], [f"not a link this tool can read: {url}. Spotify and SoundCloud "
                               f"playlists are supported"], "link")
        except LinkError as problem:
            return Linked([], [str(problem)], kind or "link")
        except OSError as problem:                      # a dead network, a 404, a timeout
            return Linked([], [f"could not open the {kind} link: {problem}"], kind or "link")

    # ---------------------------------------------------------------- Spotify

    def spotify(self, url: str) -> Linked:
        found = SPOTIFY_REF.search(str(url))
        if not found:
            raise LinkError("a Spotify playlist or album link is expected, e.g. "
                            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
        kind = found.group("kind") or found.group("kind2")
        entity = self._entity(self.fetch(SPOTIFY_EMBED.format(kind=kind, id=found.group("id"))))
        tracks = entity.get("trackList")
        if not isinstance(tracks, list) or not tracks:
            raise LinkError("the Spotify page carries no track list. A playlist that is not "
                            "public cannot be read this way")
        lines, warnings = [], []
        for track in tracks:
            title = str(track.get("title") or "").strip()
            if not title:
                continue
            artist = str(track.get("subtitle") or "").strip()
            length = _seconds(str(track.get("duration") or ""))
            lines.append(track_line(f"{artist} - {title}" if artist else title,
                                    None if length is None else int(length / 1000 + 0.5)))
        if len(tracks) >= EMBED_MAX:
            warnings.append(f"Spotify's page gives at most {EMBED_MAX} tracks and returned "
                            f"exactly that, so a longer playlist is cut here. Check the file")
        return Linked(lines, warnings, "spotify", str(entity.get("name") or ""))

    @staticmethod
    def _entity(page: str) -> dict:
        found = NEXT_DATA.search(page)
        if not found:
            raise LinkError("the Spotify embed page has no __NEXT_DATA__ block - the page "
                            "changed, so this needs a look")
        node = json.loads(found.group(1))
        for key in ENTITY_PATH:
            if not isinstance(node, dict) or key not in node:
                raise LinkError(f"the Spotify page has no {'.'.join(ENTITY_PATH)} - the page "
                                f"changed, so this needs a look")
            node = node[key]
        if not isinstance(node, dict):
            raise LinkError("the Spotify page's entity is not an object - the page changed")
        return node

    # ---------------------------------------------------------------- SoundCloud

    def soundcloud(self, url: str, tool: Optional[Path],
                   cookies_from: Optional[str] = None) -> Linked:
        if tool is None:
            raise LinkError("reading a SoundCloud link needs yt-dlp: run `py setup.py --all`")
        args = [str(tool), "--no-warnings", "--ignore-errors", "--skip-download",
                "--print", YTDLP_FIELDS]
        if cookies_from:
            args += ["--cookies-from-browser", cookies_from]
        code, output = self.run(args + [str(url)])
        lines, warnings, name = [], [], ""
        for row in output.splitlines():
            if FIELD_SEP not in row:
                continue
            fields = row.split(FIELD_SEP)
            fields += [""] * (4 - len(fields))
            playlist, title, uploader, duration = (f.strip() for f in fields[:4])
            if not name and playlist.lower() not in UNKNOWN:
                name = playlist
            if not title or title.lower() in UNKNOWN:
                continue
            # a SoundCloud title is often already "Artist - Title"; when it is not, the
            # uploader is the best guess at the artist, and may well be wrong
            track = title if " - " in title else (f"{uploader} - {title}" if
                                                  uploader.lower() not in UNKNOWN else title)
            lines.append(track_line(track, _seconds(duration)))
        if not lines:
            raise LinkError("yt-dlp returned no tracks for this link"
                            + ("" if code == 0 else f" (it exited with {code})")
                            + (". A private set needs --cookies-from-browser <browser>"
                               if not cookies_from else ""))
        if code != 0:
            warnings.append(f"yt-dlp exited with {code}: some tracks of the set may be missing")
        return Linked(lines, warnings, "soundcloud", name)
