# GitHub-hosted signed APT feed

GitHub Release assets serve a flat APT repository at:

`https://github.com/tarskisworld/pascode/releases/latest/download/`

APT follows GitHub's redirects to the latest published stable release. Each release
contains the package archive(s), Packages/Packages.gz, signed InRelease and
Release.gpg metadata, and the public archive key. No binary packages are stored in
Git history and no Pages service is required. Releases must retain previous package
assets to support clients whose signed package index is cached. Never replace an
existing version's package bytes with a different build.

The Debian package's software and image remain versioned separately from the feed
metadata. Building the feed never provisions a target or changes credentials.

## Client configuration

After the public key is reviewed and the feed is published:

```bash
sudo bash tooling/configure-apt
sudo apt update
apt-cache policy pascode
```

The configuration helper installs this checkout's public key at
`/etc/apt/keyrings/pascode.gpg` and a deb822 source at
`/etc/apt/sources.list.d/pascode.sources`, scoped with Signed-By. It verifies the
public key fingerprint and refuses differing pre-existing files. A preference
file allows pascode from this feed and rejects unrelated package names from it.
The current feed publishes amd64; arm64 is not advertised to clients until an
arm64 package is built and validated. No system trust store or existing key is
changed. APT configuration requires the user's terminal sudo prompt.

After a new version is published, use normal `sudo apt update` and
`sudo apt install --only-upgrade pascode`, followed by `/usr/bin/pascodectl setup`
to explicitly adopt its engine pin. Package updates do not silently change each
user's engine configuration or apply project declarations.

## Maintainer publication

`tooling/build-apt PACKAGE_DIRECTORY NEW_OUTPUT_DIRECTORY FINGERPRINT PASSPHRASE_FILE`
creates signed metadata with the isolated keyring selected by
`PASCODE_SIGNING_HOME`. It accepts only pascode packages. Signing credentials stay
outside Git and package images. The release signing key is separate from user
login credentials; the public key and fingerprint live under `packaging/apt/`.

The initial private key and its passphrase are encrypted in gopass under
`pascode/apt/signing-private-key` and `pascode/apt/signing-passphrase`. Materialize
them only in a private temporary directory when publishing, and remove that
directory afterwards. Do not export a signing key into an ordinary worker or a
pull-request job. No GitHub Actions signing secret or unattended publisher is
configured by this initial setup.
The generated revocation certificate is separately encrypted at
`pascode/apt/revocation-certificate`. Recovery of all three entries was verified
without displaying their contents. Use full multiline output when recovering
the private key or certificate; gopass password-only output returns only one line.

For each new version: build/test its package, download prior .deb assets from the
current stable release into a private staging directory, add the new package,
build/verify signed metadata, and upload the complete set as a draft release.
Publish only after all assets are uploaded and validated. Keep the previous
stable release intact for rollback. The latest-download URL depends on which
stable release GitHub selects as latest; publisher selection must be explicit.
`tooling/publish-apt SIGNED_FEED_DIRECTORY PUSHED_SOURCE_COMMIT` implements this
draft/upload/publish sequence and refuses to replace an existing release or omit
previous package assets. Run the isolated `tests/apt.sh SIGNED_FEED_DIRECTORY`
before publication. It verifies signatures, APT index parsing and package bytes,
and requires APT to reject a tampered index, without changing system APT settings.

The key expires after two years. Review rotation in advance and distribute a new
public key through a separately trusted channel. Release metadata intentionally
has no Valid-Until field, so an infrequently released CLI does not disable its
feed automatically; this also means signatures alone do not prevent an old signed
index being replayed. Normal APT version rules prevent silent downgrades. There
is no automatic key rotation, scheduled metadata refresh, or automatic release.
