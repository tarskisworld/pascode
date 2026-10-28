# Local packaging progress — 2026-10-20

Branch: `codex/home-installation`. Version: `0.1.0`.
Tracking: ControlPlane [home migration](https://github.com/cloisterdorateura/ControlPlane/issues/8)
and [CLI packaging](https://github.com/cloisterdorateura/ControlPlane/issues/9).

Implemented: shared home installation, versioned public CLI, documented standard
features and positional compatibility, offline Debian build and explicit setup.
System package paths: `/usr/bin/pascodectl` and `/usr/lib/pascode`.
The engine remains pinned in Docker; provider-specific images are a possible
future extension rather than an implemented plugin/runtime system.

Checks: installer repeatability and quoted paths; version/help/completion/doctor;
explicit and discovered project selection; named map output; invalid invocation
exit codes and stderr; Debian metadata, repeated setup, exact old-launcher backup,
custom-launcher preservation, real archive load and simulated missing-image setup.
The same immutable engine previously passed all 81 existing suites plus the
ControlPlane Compose worker/MCP checks and real stdio protocol probe.

The initial Debian artifact was built locally under ignored `build/`, with a SHA-256 checksum,
before the later public release. The user installed it with APT and ran explicit setup
on 2026-10-20. Independently verified: dpkg reports `install ok installed 0.1.0`,
PATH resolves `/usr/bin/pascodectl`, version reports `0.1.0`, and doctor is ready.
Setup backed up and retired the previous managed PATH launcher. APT's `_apt`
notice concerned access to the local artifact; installation completed successfully.

The existing user installation has been refreshed: `pascodectl version` and the
ControlPlane wrapper both report `0.1.0`; doctor reports ready and explicit-project
validation passes all five MainSystem contracts. The previous home dispatcher,
runtime pin file and PATH shim are backed up under
`~/.pascode/migrations/cli-0.1.0/`. The engine image is unchanged.

No local package installation step remains. The user subsequently requested an
update feed hosted by the P as code GitHub repository. Signed Release metadata,
public key/client configuration, explicit release publisher and isolated APT
acceptance/tamper/download tests are implemented. Local tests passed. Release
`v0.1.0` is public at `https://github.com/tarskisworld/pascode/releases/tag/v0.1.0`.
An isolated APT client accepted the live GitHub index and downloaded a byte-identical
87.2 MB package through the latest-release redirects. The user configured the
system feed and ran APT update successfully on 2026-10-20. Independently verified
the installed public key matches, source/preferences files exist, and APT lists
the package from the live feed. The isolated test did not change system APT
settings. Temporary signing files were removed after gopass recovery verification.
No existing login credentials or deployment state changed.
Selective ControlPlane integration remains separate; do not commit its unrelated
changes. See [APT repository governance and setup](apt-repository.md).

Source review: https://github.com/tarskisworld/pascode/pull/1 (not merged).

The user's APT run also reported a separate GitHub CLI archive-key warning.
It does not affect the P as code feed; the current official GitHub CLI keyring was
downloaded and its published SHA-256 and live signature verified for a separate
user-run system keyring refresh.

## Native distribution preview

Branch: `codex/portable-cli`; review: https://github.com/tarskisworld/pascode/pull/2.
Tracking: ControlPlane issues 11 (portable host launcher), 12 (native installers),
and 13 (clean-runner validation). The native preview uses `NATIVE_VERSION`
`0.2.0-rc.2`; the stable APT feed and `VERSION` remain at `0.1.0`.

Implemented: standard-library Go host command with Windows and Unix state locks,
Docker cancellation cleanup, selected credential forwarding, explicit setup and
doctor; SHA-256 checked per-user Unix and PowerShell installers; Linux/macOS/Windows
x86-64 and ARM64 asset builder; and six-platform GitHub Actions matrix. The local
Linux native install completed real Docker setup, five-contract offline validation,
mapping and bindings. Native Unix installer tests cover repeat install, paths with
spaces and corrupt artifacts. Both engine architecture jobs passed on the first
CI run, as did Linux and macOS native jobs. Windows repeat install found a missing
backup path in file replacement; fixed on the branch. A new full matrix is running.

All eight CI jobs passed for preview 1, including both Windows architectures and
both PowerShell editions. Its public download and checksum verification succeeded,
but a clean `setup` exposed a Docker import mismatch: the local daemon assigned a
new image ID to the verified CI-built archive. Preview 1 was withdrawn. Preview 2
records the actual local immutable ID after loading and checks the image platform.

Preview 2 completed all eight CI jobs: two engine builds, four Unix native jobs
and two Windows native jobs. Linux x86-64 and ARM64 runners both loaded their
release engine archives and passed setup/doctor. The public prerelease at
https://github.com/tarskisworld/pascode/releases/tag/v0.2.0-rc.2 has 13 assets.
An isolated Linux amd64 download verified the installer checksum, installed the
public assets, loaded the engine and passed doctor/version. GitHub still reports
`v0.1.0` as latest, so the signed APT feed is unchanged. The README now gives
clone-free installation commands. Preview 1 stays withdrawn. Remaining acceptance:
Docker Desktop execution on native macOS/Windows, publisher signing/notarization,
and tested minimum OS/runtime versions. Do not close the corresponding tasks yet.
No live Jira apply was run.

## Current follow-up — 2026-10-26

The public README and portability guide now distinguish the project's intended
scope (software with APIs) from its implemented Jira adapters. The portable CLI
review is in progress: global version reporting, CRLF legacy pins, deployment
state permissions and marker errors, selected host environment forwarding,
configuration durability, and a read-only default development mount were
revised locally. Native Go tests and vet pass. These edits are not yet part of
the published prerelease; the remaining review findings, including installer
bootstrap trust, Docker cancellation, Windows ACL handling and native Docker
Desktop validation, remain open before a further preview or task closure.
Engine setup now loads a private copy of the checked archive and checks the
platform of a preexisting image; a focused native test verifies staging and
cleanup. Native Go tests and vet pass after that follow-up.

## Merge preparation — 2026-10-28

The installation review fixes were committed on `codex/home-installation` and
merged into the portable branch. A rebuilt Debian package passed package setup,
upgrade handoff, archive loading, source-commit metadata, and overwrite refusal;
the CLI and isolated APT tests passed. The portable branch now verifies the
published preview installer and checksum manifest before execution in the public
README. Local native tests cover cancellation before the Docker CID file exists;
the pending CI run must validate Windows ACL behavior and both installers.
No pull request has been merged and no new release has been published.
