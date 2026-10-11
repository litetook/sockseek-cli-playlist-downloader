#!/usr/bin/env bash
# macOS / Linux launcher. Everything lives in run.py; this only finds Python and hands over.
set -euo pipefail
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "Python 3 is not installed."
    echo "macOS:  brew install python   or   https://www.python.org/downloads/macos/"
    echo "Linux:  install python3 with your package manager"
    exit 2
fi

version=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
case "$version" in
    3.1[0-9]|3.[2-9][0-9]) ;;
    *) echo "Python $version found, 3.10 or newer is needed." ; exit 2 ;;
esac

exec "$PY" run.py "$@"
