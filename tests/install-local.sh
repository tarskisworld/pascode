#!/usr/bin/env bash
# Exercises real host packaging without building, pulling or applying resources.
set -euo pipefail
task_source=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
task_image=${1:?Supply an existing immutable engine image}
task_tmp=$(mktemp -d)
trap 'rm -rf -- "$task_tmp"' EXIT
task_install="$task_tmp/home with spaces and 'quotes/runtime"
task_path="$task_tmp/path bin"
for task_pass in 1 2; do
  bash "$task_source/bin/install-local" "$task_image" "$task_install" "$task_path"
done
source "$task_install/runtime.env"
test "$PASCODE_IMAGE" = "$task_image"
cmp "$task_source/bin/pascodectl" "$PASCODE_CLI"
cmp "$task_source/bin/prompt-tests" "$PASCODE_PROMPT_CLI"
cmp "$task_source/bin/jira-analysis" "$PASCODE_ANALYSIS_CLI"
# Invoke from outside the checkout, with no source access in the worker.
cd "$task_tmp"
if "$task_path/pascodectl" version > "$task_tmp/usage" 2>&1; then
  echo 'Unsupported version command unexpectedly succeeded' >&2; exit 1
else
  test "$?" = 2
fi
rg -q 'Usage: pascodectl' "$task_tmp/usage"
if bash "$task_source/bin/install-local" latest "$task_tmp/rejected" "$task_path" > "$task_tmp/rejected-output" 2>&1; then
  echo 'Mutable image unexpectedly accepted' >&2; exit 1
else
  test "$?" = 2
fi
test ! -e "$task_tmp/rejected"
printf 'PASS repeat install, quoted paths, installed dispatch and immutable-image rejection\n'
