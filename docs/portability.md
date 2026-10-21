# Portable distribution requirements

The user requires installation by another person on another machine, rather than
commands specialized for the development workstation. This document reassesses
the implemented release and defines the remaining acceptance criteria. It does
not claim that the planned platforms are already supported.

## Current release evidence

Version 0.1.0 provides a Debian amd64 package and signed APT feed, validated on
Ubuntu under WSL. Its public installation commands contain no developer paths.
It still requires a running, accessible Docker daemon, Bash and GNU host utilities.
The host launchers use `flock`, `realpath`, `sha256sum` and Unix user IDs. Therefore
the current launcher is not a native Windows or macOS distribution, and the
container alone does not supply host portability. No arm64 release is published.

## Supported-platform target

Target ordinary Linux, macOS and Windows workstations on x86-64 and ARM64 where a
supported Linux-container runtime is available. Exact minimum OS/runtime versions
must be selected and tested before documenting them as supported. Windows native
and Windows through WSL are separate installation and validation paths. Arbitrary
hardware or systems that cannot run the required container runtime are outside
this target; do not advertise universal compatibility.

The engine remains in immutable Linux container images. The host interface must
handle platform paths, permissions, environment variables, process interruption,
credential injection and private deployment-state locks without Linux-only host
commands. A native cross-platform launcher is the preferred direction; its
implementation language and locking library require a focused design review.
Do not assume a file lock that works on Linux also protects Windows state.

## Repository installation contract

The public repository should provide:

- A platform support table distinguishing tested, experimental and unsupported.
- A versioned release manifest listing OS/architecture artifacts, immutable engine
  images and checksums/signatures, with a documented trust/bootstrap procedure.
- A Unix installer and a PowerShell installer that detect OS/architecture, select
  the matching verified artifact, install outside the source checkout, and expose
  the command without assuming developer paths. These scripts are planned.
- Actionable dependency diagnostics and explicit container-runtime setup guidance.
  Installing a privileged daemon or changing group membership is not implicit.
- Non-admin per-user installation where feasible; package-manager integration for
  supported systems. APT keys apply only to Debian-family installation, not every OS.
- Documented install, version, help, setup, doctor, update, uninstall and rollback
  procedures. Current version/help/setup/doctor commands exist; a universal
  installer, self-updater, uninstaller and project scaffolder do not yet exist.
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

Preserve the working 0.1.0 APT installation during this work. No new platform
artifact is published or marked supported until its acceptance criteria pass.
