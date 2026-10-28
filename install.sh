#!/bin/sh
# Native per-user release installer. No checkout, root, Bash or jq required.
set -eu
version=${PASCODE_VERSION:-0.2.0-rc.2}
printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$' || { echo 'Invalid release version' >&2; exit 2; }
case "$(uname -s)" in Linux) system=linux ;; Darwin) system=darwin ;; *) echo 'Use install.ps1 on Windows; this installer supports Linux and macOS' >&2; exit 2 ;; esac
case "$(uname -m)" in x86_64|amd64) arch=amd64 ;; arm64|aarch64) arch=arm64 ;; *) echo 'Unsupported CPU architecture' >&2; exit 2 ;; esac
root=${PASCODE_HOME:-$HOME/.pascode}
bin=${PASCODE_BIN_DIR:-$HOME/.local/bin}
mkdir -p "$root" "$bin"
root=$(cd "$root" && pwd -P)
bin=$(cd "$bin" && pwd -P)
stage=$(mktemp -d "$root/.download.XXXXXX")
trap 'rm -r -- "$stage"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
base="https://github.com/tarskisworld/pascode/releases/download/v$version"
fetch() {
  if [ -n "${PASCODE_DOWNLOAD_DIR:-}" ]; then cp "$PASCODE_DOWNLOAD_DIR/$1" "$stage/$1"
  else curl --fail --silent --show-error --location "$base/$1" --output "$stage/$1"; fi
}
hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else echo 'Install a SHA-256 tool (sha256sum or shasum)' >&2; return 1; fi
}
verify() {
  expected=$(awk -v name="$1" '$2==name {print $1}' "$stage/SHA256SUMS")
  [ ${#expected} -eq 64 ] && [ "$(hash_file "$stage/$1")" = "$expected" ] || { echo 'Release integrity check failed' >&2; exit 1; }
}
archive="pascodectl_${version}_${system}_${arch}.tar.gz"
engine="engine_linux_${arch}.tar.gz"
fetch SHA256SUMS
fetch "$archive"
verify "$archive"
fetch "$engine"
verify "$engine"
tar -tzf "$stage/$archive" > "$stage/contents"
tar -tvzf "$stage/$archive" | awk 'substr($0,1,1)!="-" {exit 1}' || { echo 'Release contains a link or other unsupported member' >&2; exit 1; }
[ "$(wc -l < "$stage/contents")" -eq 3 ] || { echo 'Release contents are incomplete or repeated' >&2; exit 1; }
while IFS= read -r name; do
  case "$name" in pascodectl|engine.json|README.md) ;; *) echo 'Unexpected archive member' >&2; exit 1 ;; esac
done < "$stage/contents"
[ "$(sort "$stage/contents" | uniq -d | wc -l)" -eq 0 ] || { echo 'Release contains duplicate members' >&2; exit 1; }
mkdir "$stage/package"
tar -xzf "$stage/$archive" -C "$stage/package"
for name in pascodectl engine.json README.md; do
  [ -f "$stage/package/$name" ] && [ ! -L "$stage/package/$name" ] || { echo 'Invalid release contents' >&2; exit 1; }
done
mv "$stage/$engine" "$stage/package/$engine"
chmod 755 "$stage/package/pascodectl"
destination="$root/versions/$version/$system-$arch"
mkdir -p "$(dirname "$destination")"
if [ -e "$bin/pascodectl" ] || [ -L "$bin/pascodectl" ]; then
  if [ ! -L "$bin/pascodectl" ]; then echo 'A custom command already exists; choose PASCODE_BIN_DIR' >&2; exit 1; fi
  target=$(readlink "$bin/pascodectl")
  case "$target" in "$root"/versions/*/pascodectl) ;; *) echo 'Existing command is not managed by this installer' >&2; exit 1 ;; esac
fi
if [ -e "$destination" ]; then
  [ "$(hash_file "$destination/pascodectl")" = "$(hash_file "$stage/package/pascodectl")" ] && \
    [ "$(hash_file "$destination/$engine")" = "$(hash_file "$stage/package/$engine")" ] && \
    cmp "$destination/engine.json" "$stage/package/engine.json" >/dev/null || { echo 'Existing version differs; refusing to replace it' >&2; exit 1; }
else mv "$stage/package" "$destination"; fi
printf '%s\n' "$root" > "$destination/.pascode-home"
ln -s "$destination/pascodectl" "$stage/pascodectl-link"
mv -f "$stage/pascodectl-link" "$bin/pascodectl"
"$bin/pascodectl" version
if [ "${PASCODE_SKIP_SETUP:-0}" = 0 ] && command -v docker >/dev/null 2>&1 && docker info --format '{{.OSType}}' 2>/dev/null | grep -qx linux; then
  "$bin/pascodectl" setup
else
  printf 'CLI installed. Start a Linux container runtime, then run: "%s/pascodectl" setup\n' "$bin"
fi
case ":$PATH:" in *":$bin:"*) ;; *) printf 'Add %s to your shell PATH. Current command: "%s/pascodectl"\n' "$bin" "$bin" ;; esac
printf 'Installed %s/%s release %s without changing project declarations or credentials.\n' "$system" "$arch" "$version"
