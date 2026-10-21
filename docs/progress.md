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
It has not been published. Host system installation is pending because sudo
requires an interactive password. Package extraction/setup has been tested in an
isolated root; this is not a claim that dpkg installed it on the host.

The existing user installation has been refreshed: `pascodectl version` and the
ControlPlane wrapper both report `0.1.0`; doctor reports ready and explicit-project
validation passes all five MainSystem contracts. The previous home dispatcher,
runtime pin file and PATH shim are backed up under
`~/.pascode/migrations/cli-0.1.0/`. The engine image is unchanged.

Next action: user installs the Debian artifact with APT and runs the explicit
system-path setup command from [the installation guide](debian-package.md).
Setup backs up/retires only the exact earlier user PATH shim, preserving custom
commands. No password should be shared in chat. Source publication and selective
ControlPlane integration remain pending authorization. Do not commit unrelated
ControlPlane changes or migrate project state or credentials.
