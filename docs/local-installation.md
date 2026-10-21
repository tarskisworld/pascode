# Shared local installation

One user installation lives in `~/.pascode`; software development stays in this
repository and each project's declarations, credentials and deployment state stay
with their existing owner. Docker stores the immutable engine image. The hidden
directory is not a Debian package, an APT repository or a second source checkout.

After an explicit image build, install without building or pulling implicitly:

```bash
bash bin/install-local IMMUTABLE_IMAGE_ID
```

The image must already exist locally and be identified by its SHA-256 ID or a
digest-pinned reference. Optional positional arguments select an installation root
and a PATH command directory; defaults are `${PASCODE_HOME:-$HOME/.pascode}` and
`$HOME/.local/bin`. The latter must already be on PATH. Installation updates the
shared runtime for all its consumers, so run offline regression checks afterwards.
There is no live apply, service restart or credential migration during installation.

Layout:

```text
~/.local/bin/pascodectl       -> invokes ~/.pascode/bin/pascodectl
~/.pascode/runtime.env        immutable engine and installed launcher pins
~/.pascode/bin/               dispatchers for CLI, prompt tests and Jira analysis
~/.pascode/packages/<sha256>/ content-addressed host launcher files
~/.pascode/migrations/        local installation backups and recovery evidence
```

Installed commands need Bash, Docker and standard host utilities, but do not need
the software source or ControlPlane checkout at runtime. Container mounts and
execution isolation remain defined by the existing content-addressed launchers.
The runtime configuration contains no credentials; it is trusted executable shell
configuration owned by the installing user. No project configuration is sourced.

The CLI preserves its existing positional contract and adds version/help,
diagnostics, named options and project discovery. See the
[Debian package and CLI contract](debian-package.md) for the feature map, standard
system paths, package setup and semantic version policy. Declaration dialects
are unchanged. `PASCODE_INSTALL_PATH_COMMAND=0` suppresses PATH shim installation
when a system package already owns the public command.

Run `bash tests/install-local.sh IMMUTABLE_IMAGE_ID` to check repeat installation,
paths with spaces and quotes, dispatch outside the checkout and rejection of
mutable image references. Run the existing container suites with a read-only
declaration fixture to validate engine behavior after a shared pin change.

For the existing machine migration, ControlPlane's `runtime.env` forwards to this
shared file. Its instance launchers and validation Compose configuration remain
environment-owned. The old `~/.local/share/pascode` directory is a compatibility
symlink to `~/.pascode/packages`; it is not another installation. Historical records
retain their original paths. Local migration backups allow restoring the old
runtime file, PATH launcher and developer build wrapper before moving packages
back to the old location.
