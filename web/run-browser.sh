#!/bin/sh
set -eu
web_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
browser_build=$(mktemp -d "${TMPDIR:-/tmp}/mauve-browser.XXXXXX")
trap 'rm -rf "$browser_build"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
python3 "$web_root/build_pages.py" --output "$browser_build/site"
printf 'Open http://127.0.0.1:%s — all processing runs in your browser.\n' "${MAUVE_BROWSER_PORT:-8766}"
python3 -u -m http.server "${MAUVE_BROWSER_PORT:-8766}" --bind 127.0.0.1 --directory "$browser_build/site"
