"""Install the external tools this one drives, at the versions pinned in dependencies.yaml.

    py setup.py            install what is missing
    py setup.py --check    only report what is there
    py setup.py --upgrade  re-pin to the newest releases, then install

Nothing is installed system-wide: the binaries land next to this file. Running it is optional -
a run that needs a missing tool offers to fetch exactly that one.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from soulseek import deps, settings

RELEASES = {"sockseek": "fiso64/sockseek", "yt-dlp": "yt-dlp/yt-dlp"}


def report(config: dict) -> int:
    rows = deps.status(config)
    if not rows:
        print(f"nothing is pinned in {deps.DEPENDENCIES_NAME}")
        return 2
    width = max(len(tool.name) for tool, _ in rows)
    print(f"platform: {deps.platform_key()}")
    for tool, state in rows:
        mark = "ok     " if state == "ok" else "MISSING"
        print(f"  {mark}  {tool.name.ljust(width)}  {tool.version}  {tool.target}")
    print(f"  python   {sys.version.split()[0]}")
    packages = deps.python_packages(config)
    print(f"  packages {', '.join(packages) if packages else 'none (standard library only)'}")
    return 0 if all(state == "ok" for _, state in rows) else 1


def latest(repo: str) -> Optional[dict]:
    """The newest release of a GitHub repo: {"tag", "assets": {name: sha256}}."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        print(f"ERROR cannot read {url}: {exc}")
        return None
    assets = {}
    for asset in data.get("assets", []):
        found = (asset.get("digest") or "").split(":")[-1]
        if found:
            assets[asset["name"]] = found
    return {"tag": (data.get("tag_name") or "").lstrip("v"), "assets": assets}


def upgrade(path: Path) -> int:
    """Rewrite the pinned versions and checksums from the newest releases.

    Only the numbers change; which asset belongs to which platform stays as written, because
    that mapping is a decision, not a fact to be discovered.
    """
    text = path.read_text(encoding="utf-8")
    config = settings.parse_yaml(text)
    for name, repo in RELEASES.items():
        release = latest(repo)
        if not release or not release["tag"]:
            return 1
        old = config.get(f"{name}.version", "?")
        if release["tag"] == old:
            print(f"{name}: already at {old}")
            continue
        print(f"{name}: {old} -> {release['tag']}")
        text = text.replace(f"{name}.version: {old}", f"{name}.version: {release['tag']}")
        for key, value in config.items():
            prefix = f"{name}."
            if not key.startswith(prefix) or not key.endswith(".asset"):
                continue
            asset = value.format(version=release["tag"])
            sha = release["assets"].get(asset)
            if sha is None:
                print(f"  WARN {asset} is not in the new release, checksum left as it was")
                continue
            sha_key = key[: -len(".asset")] + ".sha256"
            text = text.replace(f"{sha_key}: {config[sha_key]}", f"{sha_key}: {sha}")
    path.write_text(text, encoding="utf-8")
    print(f"{path.name} rewritten")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only report, install nothing")
    parser.add_argument("--upgrade", action="store_true",
                        help="re-pin dependencies.yaml to the newest releases first")
    parser.add_argument("--dependencies", type=Path,
                        default=settings.APP_DIR / deps.DEPENDENCIES_NAME)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.upgrade:
        code = upgrade(args.dependencies)
        if code:
            return code
    config = deps.load(args.dependencies)
    if args.check:
        return report(config)

    rows = deps.status(config)
    if not rows:
        print(f"nothing is pinned in {args.dependencies.name}")
        return 2
    failed = 0
    for tool, state in rows:
        if state == "ok":
            print(f"ok       {tool.name} {tool.version} -> {tool.target}")
            continue
        if not deps.install(tool, print):
            failed += 1
    if not deps.ensure_python_packages(config):
        failed += 1
    print()
    return report(config) if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
