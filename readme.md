# Bootstrap

Automating Mac configuration to be as reproducible as possible.

## Usage

On a fresh Mac, run:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/nanoxd/bootstrap/main/install)"
```

The `install` script takes care of Xcode Command Line Tools, clones (or
updates) this repo into `~/dev/bootstrap`, and then runs `make install`.
Re-running it is the canonical "update my machine" path — everything
downstream is idempotent. Override the clone location with `BOOTSTRAP_DIR`
if you want it somewhere else.

### Profiles

The bootstrap has two profiles, selected via `BOOTSTRAP_PROFILE`:

- `personal` (default) — installs the base `Brewfile` plus `Brewfile.personal`,
  which adds casks, Mac App Store apps, and other GUI-shaped stuff
- `server` — installs only the base `Brewfile` (CLI formulas)

```sh
BOOTSTRAP_PROFILE=server /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/nanoxd/bootstrap/main/install)"
```

To only run homebrew: `make brew` (honors `BOOTSTRAP_PROFILE`)

### Git commit signing

Commits are signed with SSH, not GPG. `make install` sets this up, and it can
also run on its own:

```sh
make git-signing
```

The script is safe to re-run. It generates an ED25519 key if one is missing,
loads it into the macOS Keychain-backed SSH agent, registers the public key
with GitHub as both an authentication key and a signing key, adds it to
`~/.ssh/allowed_signers` so local verification works, and configures
`~/.gitconfig.local` to sign with it. Steps that are already done are skipped,
and existing GPG keys are left untouched.

`BOOTSTRAP_SSH_KEY` overrides the key path and `BOOTSTRAP_SSH_KEY_TITLE` skips
the prompt for the key's title on GitHub.

## Customization

The scripts as is favor my needs. To avoid installing packages you don't need,
I'd recommend dumping out your own configurations on your existing PC.

### Brew

`brew bundle` ships with Homebrew and reads dependencies from a `Brewfile`.
To snapshot your current setup:

```sh
brew bundle dump --file=./Brewfile
```

### Dotfiles

The `setup` script installs dotfiles from
[nanoxd/dotfiles](https://github.com/nanoxd/dotfiles) via
[dot](https://github.com/ubnt-intrepid/dot). Edit the `dot init` call in
`setup` to point at your own repo.

## Acknowledgments

This project is heavily inspired by the following projects:

* [@thoughtbot Laptop](https://github.com/thoughtbot/laptop)
