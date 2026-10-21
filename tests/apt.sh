#!/usr/bin/env bash
# Test APT without touching /etc, system lists, installed packages or credentials.
set -euo pipefail
task_feed=${1:?Supply the signed local feed directory}
task_url=${2:-}
task_tmp=$(mktemp -d)
trap 'rm -rf -- "$task_tmp"' EXIT
mkdir -p "$task_tmp/lists/partial" "$task_tmp/archives/partial" "$task_tmp/empty" "$task_tmp/download"
cp -a --reflink=auto "$task_feed" "$task_tmp/repo"
task_repo="$task_tmp/repo"
task_key="$task_repo/pascode-archive-keyring.gpg"
gpgv --keyring "$task_key" "$task_repo/InRelease"
if [[ -z "$task_url" ]]; then task_url="file:$task_repo/"; task_tamper=true
else task_tamper=false; fi
printf 'deb [arch=amd64 signed-by=%s] %s ./\n' "$task_key" "$task_url" > "$task_tmp/sources.list"
task_apt=(-o "Dir::Etc::sourcelist=$task_tmp/sources.list" -o "Dir::Etc::sourceparts=$task_tmp/empty"
  -o "Dir::Etc::preferences=/dev/null" -o "Dir::Etc::preferencesparts=$task_tmp/empty"
  -o "Dir::Etc::trusted=/dev/null" -o "Dir::Etc::trustedparts=$task_tmp/empty"
  -o "Dir::State::lists=$task_tmp/lists" -o "Dir::Cache::archives=$task_tmp/archives"
  -o Dir::Cache::pkgcache= -o Dir::Cache::srcpkgcache=
  -o "APT::Sandbox::User=$(id -un)" -o APT::Update::Error-Mode=any -o Acquire::Languages=none)
apt-get "${task_apt[@]}" update
apt-cache "${task_apt[@]}" policy pascode > "$task_tmp/policy"
rg -Fq 'Packages' "$task_tmp/policy" || { cat "$task_tmp/policy" >&2; exit 1; }
task_package=$(find "$task_repo" -maxdepth 1 -name 'pascode_*_amd64.deb' -print | sort -V | tail -1)
task_version=$(dpkg-deb --field "$task_package" Version)
(cd "$task_tmp/download" && apt-get "${task_apt[@]}" download "pascode=$task_version")
cmp "$task_repo/pascode_${task_version}_amd64.deb" "$task_tmp/download/pascode_${task_version}_amd64.deb"
if $task_tamper; then
  sed -i 's/Label: P as code/Label: tampered/' "$task_repo/InRelease"
  if apt-get "${task_apt[@]}" update > "$task_tmp/tamper-log" 2>&1; then
    echo 'APT accepted tampered metadata' >&2; exit 1
  fi
  rg -q 'BADSIG|invalid|not signed' "$task_tmp/tamper-log"
fi
printf 'PASS isolated signed APT index, candidate and byte-identical package download\n'
