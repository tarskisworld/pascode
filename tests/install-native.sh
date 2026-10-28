#!/bin/sh
set -eu
source_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
assets=${1:?Supply the native asset directory}
assets=$(CDPATH= cd -- "$assets" && pwd)
work=$(mktemp -d)
trap 'rm -r -- "$work"' EXIT HUP INT TERM
export PASCODE_HOME="$work/home with spaces"
export PASCODE_BIN_DIR="$work/bin with spaces"
export PASCODE_DOWNLOAD_DIR="$assets"
export PASCODE_EXPECTED_MANIFEST_SHA256=$(sha256sum "$assets/SHA256SUMS" | awk '{print $1}')
export PASCODE_SKIP_SETUP=1
mkdir -p "$PASCODE_BIN_DIR"
printf '#!/bin/sh\necho custom\n' > "$PASCODE_BIN_DIR/pascodectl"
if sh "$source_root/install.sh" > "$work/conflict" 2>&1; then
  echo 'Installer replaced a custom command' >&2; exit 1
fi
grep -q 'custom command' "$work/conflict"
grep -q 'echo custom' "$PASCODE_BIN_DIR/pascodectl"
rm -- "$PASCODE_BIN_DIR/pascodectl"
sh "$source_root/install.sh"
sh "$source_root/install.sh"
"$PASCODE_BIN_DIR/pascodectl" version
test "$(cat "$(dirname "$(readlink "$PASCODE_BIN_DIR/pascodectl")")/.pascode-home")" = "$PASCODE_HOME"
"$PASCODE_BIN_DIR/pascodectl" --help > "$work/help"
grep -q 'No host Bash' "$work/help"
mkdir "$work/corrupt"
cp "$assets/SHA256SUMS" "$work/corrupt/SHA256SUMS"
case "$(uname -s)" in Linux) system=linux ;; Darwin) system=darwin ;; esac
case "$(uname -m)" in x86_64|amd64) arch=amd64 ;; arm64|aarch64) arch=arm64 ;; esac
version=$(cat "$source_root/NATIVE_VERSION")
name="pascodectl_${version}_${system}_${arch}.tar.gz"
printf 'corrupted' > "$work/corrupt/$name"
if PASCODE_DOWNLOAD_DIR="$work/corrupt" sh "$source_root/install.sh" > "$work/rejected" 2>&1; then
  echo 'Installer accepted corrupt release bytes' >&2; exit 1
fi
grep -q 'integrity check failed' "$work/rejected"
printf 'PASS native Unix installer, repeat install, paths with spaces and checksum rejection\n'
