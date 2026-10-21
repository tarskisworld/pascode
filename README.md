# P as code software

Container-backed configuration tooling with a shared CLI, per-project declarations
and a signed APT update feed. Current release: **0.1.0**.

**Current tested distribution:** Debian/Ubuntu amd64, including Ubuntu under WSL,
with a working Docker daemon. Native Windows, macOS and ARM64 installers are not
yet available. See the [cross-platform distribution requirements](docs/portability.md)
for the reassessment and acceptance plan; containerized execution does not make
the current Linux host launcher portable by itself.

## Install on Debian or Ubuntu

Currently supported package architecture: **amd64**, including Ubuntu on WSL.
Have Docker installed and running, your user authorized to access it, and `curl`
and CA certificates available. No source checkout or personal home path is needed.

Run this block in **Bash**. It downloads the public key, verifies its pinned
SHA-256, adds the scoped repository, installs the package and configures your user.
The parentheses keep shell settings and temporary variables out of your shell.

```bash
(
  set -euo pipefail
  pascode_keyring=$(mktemp)
  trap 'rm -- "$pascode_keyring"' EXIT
  curl -fsSL https://github.com/tarskisworld/pascode/releases/latest/download/pascode-archive-keyring.gpg -o "$pascode_keyring"
  printf '2b6da0a3d20700300afaa4532a78a9e479b074441f573f92bcb9faa147d6d676  %s\n' "$pascode_keyring" | sha256sum --check -
  sudo install -d -m 0755 /etc/apt/keyrings
  sudo install -m 0644 "$pascode_keyring" /etc/apt/keyrings/pascode.gpg
  printf '%s\n' \
    'Types: deb' \
    'URIs: https://github.com/tarskisworld/pascode/releases/latest/download/' \
    'Suites: ./' \
    'Architectures: amd64' \
    'Signed-By: /etc/apt/keyrings/pascode.gpg' \
    | sudo tee /etc/apt/sources.list.d/pascode.sources >/dev/null
  printf '%s\n' \
    'Package: pascode' \
    'Pin: release o=pascode' \
    'Pin-Priority: 500' \
    '' \
    'Package: *' \
    'Pin: release o=pascode' \
    'Pin-Priority: -1' \
    | sudo tee /etc/apt/preferences.d/pascode >/dev/null
  sudo apt update
  sudo apt install pascode
  /usr/bin/pascodectl setup
  hash -r
  /usr/bin/pascodectl version
  /usr/bin/pascodectl doctor
)
hash -r
```

Use sudo only for system installation and APT configuration; run setup as your
ordinary user. Re-running the block refreshes only the pascode-owned key/source/
preference files and package setup. For a checkout-based helper that refuses
differing existing APT files, see [APT setup](docs/apt-repository.md).

## Upgrade

```bash
sudo apt update
sudo apt install --only-upgrade pascode
/usr/bin/pascodectl setup
pascodectl doctor
```

Normal `sudo apt upgrade` also upgrades the package. Setup deliberately adopts the
new engine for the current user; package installation does not silently repin
every user's runtime. See [release notes](CHANGELOG.md) and
[key governance and rollback](docs/apt-repository.md).

## Use

```bash
pascodectl version
pascodectl --help
pascodectl doctor
pascodectl validate --project /path/to/project/.pascode
```

Without an explicit project path, commands search the current directory and its
ancestors for `.pascode/jira-as-code` or `jira-as-code`. Existing schemas must use
a supported declaration dialect; there is no project-scaffolding command yet.
Validate/map are offline. Live plan/apply/verify require explicit state, bindings
and selected target authentication.

System files live under `/usr/bin` and `/usr/lib/pascode`. User configuration is
`$HOME/.pascode` (equivalently `~/.pascode`); it is not a cache and is not under
`$XDG_CACHE_HOME`. The command uses `PASCODE_HOME` only when you explicitly select
another user configuration root. No HOME environment setting needs to be changed.
Project declarations and private deployment state remain separately owned.

## Development and architecture

Reusable validation, Jira shape mapping, binding generation, deployment and audit
code extracted from ControlPlane. This independent local repository is the `pascode` software source owned by
`tarskisworld`. It does not replace any instance declaration repository. No GitHub
repository was created, and no source was pushed during extraction.

The Dockerfile pins Python, locked Python dependencies and Terraform 1.14.4 by
digest. It contains no declarations, credentials, state, naming database or Docker
socket. `bin/pascodectl` is the host launcher; set `PASCODE_IMAGE` to the immutable
image ID/digest. Normal commands run packaged code, with no source bind mount.
An explicit development build can be made with `docker build --iidfile IMAGE_ID .`.
The environment integration installs the launcher by content hash and pins the image.

The shared user installation now lives in `~/.pascode`, independently of the
ControlPlane source checkout. See [local installation](docs/local-installation.md)
for installation, layout, compatibility paths and recovery boundaries.

The CLI is versioned from `VERSION` using semantic versioning. `pascodectl version`
and `pascodectl --help` work without starting Docker. An offline Debian package
provides the standard `/usr/bin/pascodectl` installation; see the
[package and CLI contract](docs/debian-package.md) for setup, feature coverage,
upgrades and the previous-launcher handoff.

The [signed APT feed](docs/apt-repository.md) is hosted using this repository's
GitHub Release assets. One-time client configuration scopes its public signing
key and permits only the pascode package from the feed. Package upgrades use
standard APT; adopting an upgraded engine remains explicit per-user setup.

Commands retain validate/map/bindings/plan/apply/verify and positional arguments.
Offline work is networkless. Deployment Python and Terraform jobs receive only
selected credentials/bindings and the private work directory. Host locking still
protects that directory. Terraform is containerized by default; an explicit
`PASCODE_TERRAFORM_BINARY` retains the existing host-binary compatibility contract.
State must remain outside Git. No automatic reconciliation is introduced.

The read-only MCP deliberately retains the existing BRB/CDT target interface.
Environment configuration supplies their mounts. MainSystem uses JSON text valid
as YAML with JSON schemas; BRB/CDT use their existing YAML schema dialect. Packaging
does not make those dialects execution-compatible or resolve missing schemas.

Existing tests: `/app/tests.py`, `/app/mcp_tests.py`, `/runtime/tests.py`,
`/runtime/adapter_tests.py`, `/runtime/deployment_tests.py`. Execution tests consume
an explicit declaration fixture mounted read-only at `/inputs`. They make no live
Jira calls. `worker.py` CLI uses `--root` and `--schema-root`; `runner.py` implements
offline validate/map. Persistent state and historical instance evidence remain
with their owning environment/declaration repositories.

`legacy-jira/` centralizes six existing YAML-dialect mapping/analysis/generation
implementations previously copied across CDT and BRB. Instance scripts are now
compatibility wrappers; site/account labels and historical samples remain instance
inputs. See `legacy-jira/README.md` and its extraction audit. `bin/jira-analysis`
runs those commands in the pinned offline image with explicit input/output mounts.
