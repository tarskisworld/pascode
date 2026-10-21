#!/bin/sh
# Verify a release archive can be adopted on a different Docker daemon.
set -eu
source_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
assets=${1:?Supply the native asset directory}
assets=$(CDPATH= cd -- "$assets" && pwd)
work=$(mktemp -d)
trap 'rm -r -- "$work"' EXIT HUP INT TERM
export PASCODE_HOME="$work/home"
export PASCODE_BIN_DIR="$work/bin"
export PASCODE_DOWNLOAD_DIR="$assets"
export PASCODE_SKIP_SETUP=1
sh "$source_root/install.sh" > "$work/install.log"
"$PASCODE_BIN_DIR/pascodectl" setup
"$PASCODE_BIN_DIR/pascodectl" doctor
printf 'PASS native engine archive import and immutable local pin\n'
