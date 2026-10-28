# P as code

P as code is for managing software configuration through APIs using declarations
in files. The goal is to support any software with an API. Keep each project's
declarations in its own repository, check them locally, and review a plan before
applying changes. The command runs its Python and Terraform engine in a pinned
Linux container, so a normal install does not require a source checkout or those
tools on your host.

**Current implementation:** the available validation, mapping, bindings and
deployment adapters focus on Jira. Support for another service requires adapters
for its API and declaration schema; installing the CLI alone does not add that
support. The current Jira adapters do not cover every Jira setting, and the CLI
does not create a new declaration project structure for you.

## Choose an installation

| Platform | Release | Status |
| --- | --- | --- |
| Debian or Ubuntu on x86-64, including WSL | 0.1.0 via signed APT repository | Stable distribution |
| Linux, macOS or Windows on x86-64 or ARM64 | 0.2.0-rc.2 native installer | Preview |

Both routes need Docker with an accessible **Linux-container daemon** for setup
and engine commands. Your user must be able to use Docker. Installation does not
change Docker permissions or install Docker for you. The native preview has passed
installer and CLI checks on all six OS/CPU combinations; engine setup has been
verified on Linux x86-64 and ARM64. Docker Desktop engine execution on native
macOS and Windows is still being validated.

### Debian or Ubuntu: stable APT release

Run this block in Bash. It checks the repository signing key before configuring a
source restricted to the `pascode` package. You do not need to clone this repo.

```bash
(
  set -euo pipefail
  pascode_tmp=$(mktemp -d)
  trap 'rm -rf -- "$pascode_tmp"' EXIT
  pascode_keyring="$pascode_tmp/keyring.gpg"
  curl -fsSL https://github.com/tarskisworld/pascode/releases/latest/download/pascode-archive-keyring.gpg -o "$pascode_keyring"
  printf '2b6da0a3d20700300afaa4532a78a9e479b074441f573f92bcb9faa147d6d676  %s\n' "$pascode_keyring" | sha256sum --check -
  printf '%s\n' \
    'Types: deb' \
    'URIs: https://github.com/tarskisworld/pascode/releases/latest/download/' \
    'Suites: ./' \
    'Architectures: amd64' \
    'Signed-By: /etc/apt/keyrings/pascode.gpg' \
    > "$pascode_tmp/pascode.sources"
  printf '%s\n' \
    'Package: pascode' \
    'Pin: release o=pascode' \
    'Pin-Priority: 500' \
    '' \
    'Package: *' \
    'Pin: release o=pascode' \
    'Pin-Priority: -1' \
    > "$pascode_tmp/pascode.pref"
  for pascode_pair in \
    "$pascode_keyring:/etc/apt/keyrings/pascode.gpg" \
    "$pascode_tmp/pascode.sources:/etc/apt/sources.list.d/pascode.sources" \
    "$pascode_tmp/pascode.pref:/etc/apt/preferences.d/pascode"; do
    pascode_source=${pascode_pair%%:*}
    pascode_target=${pascode_pair#*:}
    if sudo test -e "$pascode_target" && ! sudo cmp -s "$pascode_source" "$pascode_target"; then
      printf 'Existing APT file differs: %s\n' "$pascode_target" >&2
      exit 2
    fi
  done
  sudo install -d -m 0755 /etc/apt/keyrings /etc/apt/sources.list.d /etc/apt/preferences.d
  sudo install -m 0644 "$pascode_keyring" /etc/apt/keyrings/pascode.gpg
  sudo install -m 0644 "$pascode_tmp/pascode.sources" /etc/apt/sources.list.d/pascode.sources
  sudo install -m 0644 "$pascode_tmp/pascode.pref" /etc/apt/preferences.d/pascode
  sudo apt update
  sudo apt install pascode
  /usr/bin/pascodectl setup
  /usr/bin/pascodectl doctor
)
```

The `sudo` steps configure APT and install the package. Run `setup` as your
ordinary user. Later upgrades use normal APT commands; run `pascodectl setup`
after an upgrade to adopt its engine for your user. See the [APT repository
notes](docs/apt-repository.md) for key management, rollback and removal.
Re-running the block preserves identical APT files and refuses to overwrite
differing administrator-managed files.

### Linux or macOS: native preview

```sh
(
  set -eu
  pascode_stage=$(mktemp -d)
  trap 'rm -r -- "$pascode_stage"' EXIT
  pascode_base=https://github.com/tarskisworld/pascode/releases/download/v0.2.0-rc.2
  for pascode_file in install.sh SHA256SUMS; do
    curl -fsSL "$pascode_base/$pascode_file" -o "$pascode_stage/$pascode_file"
  done
  pascode_hash() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
    else shasum -a 256 "$1" | awk '{print $1}'; fi
  }
  [ "$(pascode_hash "$pascode_stage/install.sh")" = 63d56cf9f18481f07313822555b8d7895b26a53e20e84d7b14e59e502622e636 ]
  [ "$(pascode_hash "$pascode_stage/SHA256SUMS")" = e4c5a12dceb1709cf9c86ebd0712f5a4de4c86ffcb9108139a255f21229282b3 ]
  case "$(uname -s)" in Linux) pascode_os=linux ;; Darwin) pascode_os=darwin ;; *) exit 2 ;; esac
  case "$(uname -m)" in x86_64|amd64) pascode_arch=amd64 ;; arm64|aarch64) pascode_arch=arm64 ;; *) exit 2 ;; esac
  for pascode_file in "pascodectl_0.2.0-rc.2_${pascode_os}_${pascode_arch}.tar.gz" "engine_linux_${pascode_arch}.tar.gz"; do
    curl -fsSL "$pascode_base/$pascode_file" -o "$pascode_stage/$pascode_file"
  done
  PASCODE_DOWNLOAD_DIR="$pascode_stage" sh "$pascode_stage/install.sh"
)
"$HOME/.local/bin/pascodectl" doctor
```

The fixed hashes above pin the installer and manifest for this preview; the
installer verifies the platform package and engine against that manifest before
installing under `~/.pascode`. If Docker is not ready yet,
run `"$HOME/.local/bin/pascodectl" setup` after starting a Linux-container daemon.
The installer prints PATH guidance if `~/.local/bin` is not already on your PATH.

### Windows: native preview

Run in PowerShell:

```powershell
$pascodeStage = Join-Path ([IO.Path]::GetTempPath()) ('pascode-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $pascodeStage | Out-Null
try {
  $pascodeBase = 'https://github.com/tarskisworld/pascode/releases/download/v0.2.0-rc.2'
  foreach ($name in @('install.ps1','SHA256SUMS')) {
    Invoke-WebRequest -UseBasicParsing -Uri "$pascodeBase/$name" -OutFile (Join-Path $pascodeStage $name)
  }
  if ((Get-FileHash -Algorithm SHA256 (Join-Path $pascodeStage 'install.ps1')).Hash -ine '2adce3729089c0adf663e9f3cc2ab007f2b094ea7dbb02a727ba283a89ef5f30') { throw 'Installer checksum mismatch' }
  if ((Get-FileHash -Algorithm SHA256 (Join-Path $pascodeStage 'SHA256SUMS')).Hash -ine 'e4c5a12dceb1709cf9c86ebd0712f5a4de4c86ffcb9108139a255f21229282b3') { throw 'Manifest checksum mismatch' }
  $pascodeArch = switch ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()) { 'x64' { 'amd64' } 'arm64' { 'arm64' } default { throw 'Unsupported CPU' } }
  foreach ($name in @("pascodectl_0.2.0-rc.2_windows_$pascodeArch.zip", "engine_linux_$pascodeArch.tar.gz")) {
    Invoke-WebRequest -UseBasicParsing -Uri "$pascodeBase/$name" -OutFile (Join-Path $pascodeStage $name)
  }
  & (Join-Path $pascodeStage 'install.ps1') -DownloadDirectory $pascodeStage
} finally { Remove-Item -LiteralPath $pascodeStage -Recurse -Force }
& "$env:USERPROFILE\.pascode\bin\pascodectl.exe" doctor
```

The installer adds its command directory to your user PATH for future terminals.
If Docker Desktop is not ready, run `setup` with the installed command after
starting Docker in Linux-container mode. The executable is currently unsigned,
so Windows may show a publisher warning. The macOS preview is not notarized.
These preview installers verify downloaded assets with SHA-256; that check does
not establish a verified software publisher.

## Use an existing declaration project

Check the installation, then point the command at the root of a supported
P as code declaration project:

```sh
pascodectl version
pascodectl doctor
pascodectl validate --project /path/to/declarations
pascodectl map --project /path/to/declarations --output /path/to/output
pascodectl bindings --project /path/to/declarations --output /path/to/output
```

`validate`, `map` and `bindings` run offline, without contacting the target API. If you run
a command inside a project, P as code also searches the current directory and its
parents for `.pascode/jira-as-code` or `jira-as-code` declarations. Use
`pascodectl --help` for commands and options.

`plan`, `apply` and `verify` are separate live operations. They require explicit
bindings, a private state directory outside Git, and credentials for the selected
Jira target. Review the plan before applying it. Keep credentials and deployment
state with the owning project, outside this software repository and its images.

The shared user configuration lives in `~/.pascode`; it is persistent configuration,
not a cache. Native installers keep versions there for explicit upgrades and
rollback. See [native distribution status](docs/portability.md) for tested behavior
and remaining platform work.

## Development and project status

This repository contains the reusable CLI, engine, validation, mapping, bindings,
deployment and audit code. Project declarations and target-specific evidence live
in independent repositories. The [package and CLI contract](docs/debian-package.md)
explains the stable package; the [changelog](CHANGELOG.md) records stable releases.
The [native launcher review](https://github.com/tarskisworld/pascode/pull/2)
and [preview release](https://github.com/tarskisworld/pascode/releases/tag/v0.2.0-rc.2)
record the cross-platform work. No live Jira deployment is implied by
installing the CLI.

Report problems or request features in the [ControlPlane issue tracker](https://github.com/cloisterdorateura/ControlPlane/issues),
which tracks this project's work. This repository does not currently include a
license file.
