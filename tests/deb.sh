#!/usr/bin/env bash
set -euo pipefail
task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
task_deb=${1:?Supply the built Debian package}
task_tmp=$(mktemp -d)
trap 'rm -rf -- "$task_tmp"' EXIT
test "$(dpkg-deb --field "$task_deb" Package)" = pascode
test "$(dpkg-deb --field "$task_deb" Version)" = "$(cat "$task_root/VERSION")"
dpkg-deb --extract "$task_deb" "$task_tmp/root"
task_lib="$task_tmp/root/usr/lib/pascode"
source "$task_lib/engine.env"
task_image=$PASCODE_IMAGE
test "$(dpkg-deb --field "$task_deb" Architecture)" = "$(docker image inspect "$task_image" --format '{{.Architecture}}')"
task_cli="$task_tmp/root/usr/bin/pascodectl"
task_user="$task_tmp/user"
mkdir -p "$task_user"
export PASCODE_HOME="$task_user/.pascode" PASCODE_USER_BIN_DIR="$task_user/.local/bin"
# A previous source-based user launcher is retired only after a backup.
bash "$task_root/bin/install-local" "$task_image"
test -f "$PASCODE_USER_BIN_DIR/pascodectl"
"$task_cli" setup
test ! -e "$PASCODE_USER_BIN_DIR/pascodectl"
test -f "$PASCODE_HOME/migrations/package-setup/pascodectl"
"$task_cli" setup
"$task_cli" version --json > "$task_tmp/version"
test "$(cat "$task_tmp/version")" = "$(printf '{"name":"pascodectl","version":"%s"}' "$(cat "$task_root/VERSION")")"
"$task_cli" doctor --json > "$task_tmp/doctor"
rg -q '"ready":true' "$task_tmp/doctor"
# Custom launchers must never be retired by setup.
printf '#!/bin/sh\necho custom\n' > "$PASCODE_USER_BIN_DIR/pascodectl"
"$task_cli" setup
rg -q 'echo custom' "$PASCODE_USER_BIN_DIR/pascodectl"
# The archive is real and loadable; importing the same immutable image is idempotent.
docker load --input "$task_lib/engine.tar.gz" > "$task_tmp/load"
docker image inspect "$task_image" >/dev/null
# Exercise missing-image setup with an isolated Docker CLI double. Never remove a
# real engine image just to test this branch.
mkdir -p "$task_tmp/fake-bin"
cat > "$task_tmp/fake-bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
  'image inspect') test -f "$PASCODE_TEST_IMAGE_LOADED" ;;
  'load --input') test -s "$3"; touch "$PASCODE_TEST_IMAGE_LOADED" ;;
  *) exit 99 ;;
esac
EOF
chmod 755 "$task_tmp/fake-bin/docker"
PASCODE_TEST_IMAGE_LOADED="$task_tmp/image-loaded" PATH="$task_tmp/fake-bin:$PATH" "$task_cli" setup
test -f "$task_tmp/image-loaded"
printf 'PASS Debian metadata, setup/upgrade, launcher handoff, archive load and missing-image setup\n'
