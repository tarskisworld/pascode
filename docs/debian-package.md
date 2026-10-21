# Debian installation and CLI contract

The local `pascode` Debian package owns `/usr/bin/pascodectl`, implementation
files and its offline engine archive under `/usr/lib/pascode`, documentation
under `/usr/share/doc/pascode`, and Bash completion under
`/usr/share/bash-completion/completions`. Docker stores loaded images. User
configuration and installed runtime pins remain under `~/.pascode`; project
declarations, credentials and deployment state remain separately owned.

Build an artifact from an existing local immutable image:

```bash
bash tooling/build-deb IMMUTABLE_IMAGE_ID
```

The package architecture follows the engine image (amd64 or arm64). The builder
does not fetch an image, publish a package, or apply project configuration.
The package includes the saved image so a new machine need not clone source or
download an unpublished image. Build the source Dockerfile explicitly to create
an engine first, or transfer a previously reviewed image. The versioned Dockerfile
pins its base images, Python dependencies and Terraform.

On a compatible Debian/Ubuntu machine with a running Docker daemon:

```bash
sudo apt install ./pascode_0.1.0_amd64.deb
/usr/bin/pascodectl setup
hash -r
pascodectl version
pascodectl doctor
```

Enter a sudo password only into the terminal's password prompt. The user running
setup must already be authorized to use Docker. Setup does not change Docker group
membership, daemon settings, credentials, or shell profiles. Package installation
has no maintainer scripts: it does not start Docker or load images as root. Setup
explicitly loads the packaged archive if needed, then updates that user's pinned
runtime and host launchers without adding another PATH shim.

For the migration, setup backs up and retires only the exact user PATH launcher
created by the previous installer. Custom launchers and symlinks are preserved;
their owner must choose whether to retire them. The backup lives under
`~/.pascode/migrations/package-setup/`. Existing compatibility package links and
ControlPlane's runtime forwarder remain valid. Run setup again after upgrading
the Debian package to deliberately adopt its engine and refresh user launchers.

Removing the package removes its system files, not home configuration, project
state or Docker images. To return to the user installation, restore the backed-up
PATH launcher; its installed files remain under `~/.pascode`. No destructive purge
hook or automatic Docker image cleanup is supplied.

## Standard CLI feature map

| Feature | Current contract |
|---|---|
| Semantic version | `VERSION`, initially `0.1.0`; `version`, `--version`, `-V` |
| Help | No arguments, `help`, `help COMMAND`, `COMMAND --help` |
| Named options | `--project`/`-C`, `--output`/`-o`, `--bindings`, `--state-dir` |
| Existing commands | validate, map, bindings, plan, apply, verify; positional compatibility retained |
| Project discovery | Explicit path first; otherwise nearest ancestor with `.pascode/jira-as-code` or `jira-as-code` |
| Machine output | `--json` for version/doctor; validate/map already emit JSON |
| Diagnostics | `doctor` checks host dependencies, Docker access and immutable local engine |
| Completion | `completion bash`, plus packaged Bash completion file |
| Installation | Explicit `setup`, no implicit network download or live apply |
| Exit status | 0 success, 1 failed check, 2 usage; other engine/Docker statuses preserved |
| Credentials | Existing selected-target runtime injection; never embedded in package |

Project discovery only selects an existing directory; it does not create schemas,
convert dialects, fetch parent configurations, or interpret arbitrary project code.
Explicit output/state/bindings paths are resolved relative to the caller's current
directory. Live commands still require explicit private state, bindings and target
authentication. `plan` can query a live target and is not an offline command.

Versioning follows SemVer: patch releases fix compatible behavior; minor releases
add compatible commands/options; major releases may break the documented CLI
contract. During 0.x development a minor release may introduce documented breaking
changes. The package version and reported CLI version derive from the same file.
The immutable engine ID is a separate runtime pin, not a semantic version alias.
The build currently accepts stable three-part versions; prerelease publishing,
self-update and project scaffolding are future work. The
[signed APT feed](apt-repository.md) supplies normal package-manager updates.

The builder writes a sibling `.deb.sha256` checksum. Verify it with
`sha256sum -c pascode_0.1.0_amd64.deb.sha256` from the artifact directory before
installation. `PASCODE_HOME` can select an isolated user configuration root;
`PASCODE_USER_BIN_DIR` selects the previous-user-launcher directory for explicit
local installations and migration (default `~/.local/bin`).

No remote repository is published by building this package. Existing container
validation/execution suites and host CLI/package checks must pass before release.
