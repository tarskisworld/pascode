#!/usr/bin/env bash
set -euo pipefail
task_source=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
task_image=${1:?Supply an existing immutable engine image}
task_fixture=${2:?Supply the supported MainSystem declaration fixture}
task_tmp=$(mktemp -d)
trap 'rm -rf -- "$task_tmp"' EXIT
bash "$task_source/bin/install-local" "$task_image" "$task_tmp/runtime" "$task_tmp/path"
task_cli="$task_tmp/path/pascodectl"
test "$("$task_cli" --version)" = "pascodectl $(cat "$task_source/VERSION")"
test "$("$task_cli" version --json)" = "$(printf '{"name":"pascodectl","version":"%s"}' "$(cat "$task_source/VERSION")")"
"$task_cli" > "$task_tmp/help"
rg -q 'Usage:' "$task_tmp/help"
"$task_cli" help validate > "$task_tmp/help-command"
rg -q 'Help for validate' "$task_tmp/help-command"
"$task_cli" completion bash > "$task_tmp/completion"
bash -n "$task_tmp/completion"
"$task_cli" doctor --json > "$task_tmp/doctor"
rg -q '"ready":true' "$task_tmp/doctor"
mkdir -p "$task_tmp/project/nested"
ln -s "$task_fixture" "$task_tmp/project/.pascode"
cd "$task_tmp/project/nested"
"$task_cli" validate > "$task_tmp/discovered"
"$task_cli" validate --project "$task_fixture" --json > "$task_tmp/explicit"
cmp "$task_tmp/discovered" "$task_tmp/explicit"
"$task_cli" map --project "$task_fixture" --output "$task_tmp/mapped" > "$task_tmp/map-output"
test -f "$task_tmp/mapped/projects.tf.json"
test -f "$task_tmp/mapped/rest-plan.json"
for task_case in unknown missing-option extra-path unsupported-json missing-state; do
  case "$task_case" in
    unknown) task_args=(--json unknown) ;;
    missing-option) task_args=(--json validate --project) ;;
    extra-path) task_args=(--json validate "$task_fixture" extra) ;;
    unsupported-json) task_args=(--json setup) ;;
    missing-state) task_args=(plan --project "$task_fixture") ;;
  esac
  if "$task_cli" "${task_args[@]}" > "$task_tmp/stdout" 2> "$task_tmp/stderr"; then
    echo 'Invalid invocation unexpectedly succeeded' >&2; exit 1
  else test "$?" = 2; fi
  test ! -s "$task_tmp/stdout"
  if [[ "$task_case" == missing-state ]]; then rg -q 'private state directory' "$task_tmp/stderr"
  else rg -q '^\{"error":"usage"' "$task_tmp/stderr"; fi
done
printf 'PASS CLI version/help/completion/doctor/discovery/named options/error streams\n'
