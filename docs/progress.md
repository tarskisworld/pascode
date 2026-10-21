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

The Debian artifact is local under ignored `build/`, with a SHA-256 checksum.
It has not been published. The user installed it with APT and ran explicit setup
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
87.2 MB package through the latest-release redirects. The user's one-time sudo
APT configuration remains pending; system APT settings were not changed by the
test. Temporary signing files were removed after gopass recovery verification.
No existing login credentials or deployment state changed.
Selective ControlPlane integration remains separate; do not commit its unrelated
changes. See [APT repository governance and setup](apt-repository.md).

Source review: https://github.com/tarskisworld/pascode/pull/1 (not merged).
