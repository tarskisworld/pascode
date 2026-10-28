# Portable distribution requirements

P as code is intended to manage software configuration through APIs across
services. Jira is the first implemented adapter, not the product boundary.
Installing the CLI does not confer support for a service without an adapter and
declaration schema.

Users need to install the CLI on their own machines using commands that do not
depend on the development workstation. This document records the
implemented native preview and the remaining acceptance criteria. Version 0.1.0
remains the published stable release; native preview 0.2.0-rc.2 is published as a
prerelease.

## Current release evidence

Version 0.1.0 provides a Debian amd64 package and signed APT feed, validated on
Ubuntu under WSL. Its public installation commands contain no developer paths.
It still requires a running, accessible Docker daemon, Bash and GNU host utilities.
The host launchers use `flock`, `realpath`, `sha256sum` and Unix user IDs. Therefore
the stable launcher is not a native Windows or macOS distribution, and the
container alone does not supply host portability. The separate 0.2.0-rc.2
prerelease provides native artifacts for Linux, macOS and Windows on x86-64
and ARM64.

## Supported-platform target

Target ordinary Linux, macOS and Windows workstations on x86-64 and ARM64 where a
supported Linux-container runtime is available. Exact minimum OS/runtime versions
must be selected and tested before documenting them as supported. Windows native
and Windows through WSL are separate installation and validation paths. Arbitrary
hardware or systems that cannot run the required container runtime are outside
this target; do not advertise universal compatibility.

The engine remains in immutable Linux container images. The new Go host launcher
implements platform paths, private deployment-state locks, process cancellation,
and selected credential forwarding without requiring Go on the user's machine.
The Unix and Windows locking implementations are separate. Go is a distribution
choice, not a new engine or provider language; Python and Terraform remain inside
the container.

## Repository installation contract

The public repository should provide:

- A platform support table distinguishing tested, experimental and unsupported.
- A versioned release manifest listing OS/architecture artifacts, immutable engine
  images and checksums/signatures, with a documented trust/bootstrap procedure.
- A Unix installer and a PowerShell installer that detect OS/architecture, select
  matching SHA-256-checked artifacts, install outside the source checkout, and
  expose the command without assuming developer paths. Both scripts are implemented
  for a published prerelease; native Docker Desktop checks remain.
- Actionable dependency diagnostics and explicit container-runtime setup guidance.
  Installing a privileged daemon or changing group membership is not implicit.
- Non-admin per-user installation where feasible; package-manager integration for
  supported systems. APT keys apply only to Debian-family installation, not every OS.
- Documented install, version, help, setup, doctor, update, uninstall and rollback
  procedures. Version/help/setup/doctor commands and versioned native installs
  exist; self-update, an uninstaller and project scaffolding do not yet exist.
- Existing-project validation examples plus explicit declaration-dialect limits.
  Installing software must not require another person's contracts or credentials.

A new user should not need to clone ControlPlane, build an image, set developer
environment variables or know an internal image ID for a normal release install.
The source checkout/build path remains a separate contributor workflow.

## Dependency-ordered implementation

1. **Portable host launcher.** Preserve current CLI behavior and security boundaries;
   remove GNU/Bash dependencies from the end-user launcher; test paths with spaces,
   Windows drive paths, user directories, cancellation and actual state locking.
2. **Release artifacts and installers.** Build native launchers for the supported
   matrix and engine images for each supported CPU; provide manifests, verified
   installers, PATH guidance, upgrade/removal and recovery. Keep APT as one route.
3. **Clean-machine acceptance.** Exercise installation from published artifacts on
   Linux, macOS and Windows runners/users, with no development checkout or existing
   user configuration. Test missing Docker, wrong architecture, failed integrity
   checks, existing installations, upgrades, rollback and offline usage. Live
   container execution needs separate proof where hosted runners lack a usable
   Linux-container runtime. Cross-compilation alone is not acceptance evidence.

## Evidence and gaps for the native preview

The native Linux launcher completed setup against the local Docker daemon, then
validated five existing fixture contracts and generated mapping and bindings.
These checks make no live provider calls. GitHub Actions build x86-64 and ARM64
Linux engines and run native tests and installer checks on Linux, macOS and Windows
runners. All six native runner checks pass for preview 2. Preview 1 was withdrawn
after a public download test found a Docker import ID difference. Preview 2 verifies
the loaded platform and records the local immutable ID. Linux CI imports the engine
on both CPU architectures and passes setup/doctor. An isolated public download of
preview 2 also passed checksum verification, installation, setup, doctor and version
on Linux amd64. Hosted macOS and Windows checks exercise their native commands
and installers without Docker Desktop; container execution there still needs
separate evidence. The Windows executable is unsigned, so a publisher warning may
appear. Signing requires a certificate and distribution policy before a general
release; checksum verification alone does not establish publisher identity.

Preserve the working 0.1.0 APT installation during this work. No new platform
artifact is marked generally supported until its acceptance criteria pass.

## Preview installation lifecycle

The native installers retain each installed version under the user's `.pascode`
directory. Re-run the same versioned installer to verify an existing installation;
use a newer versioned installer to upgrade. Setup explicitly adopts its bundled
engine for that user. To roll back, run the installer for a previous healthy
published version and then run setup and doctor. Do not roll back deployment state
without checking compatibility with the older engine. Withdrawn preview 1 is not
a rollback target.

On Unix the command is a managed link in `~/.local/bin` and its version directory
records the selected user configuration root. On Windows the managed executable
and configuration-root record live in `%USERPROFILE%\.pascode\bin` by default.
This lets a later shell use a custom installation location. To remove a preview, first
stop using the command, then remove only that managed command and the corresponding
version directory. On Windows also remove the managed record, `engine.json` and
`.pascode-home` beside the command. Leave `config.json`, credentials and per-project deployment
state in place unless the owner explicitly chooses to remove them. The Unix
installer refuses to replace a custom command; the Windows installer checks its
managed record and executable hash before replacement. Package-manager installs
on Debian/Ubuntu have their own APT removal path.
