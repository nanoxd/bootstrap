# Bootstrap

Automating Mac configuration to be as reproducible as possible.

## Usage

On a fresh Mac, run:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/nanoxd/bootstrap/main/install)"
```

For the personal profile, bootstrap first opens the [1Password download page](https://1password.com/downloads/mac/)
and waits for you to install it and sign in. If the app is already installed,
this step is skipped. The desktop app manages its own updates.

The `install` script takes care of Xcode Command Line Tools, clones (or
updates) this repo into `~/dev/bootstrap`, and then runs `make install`.
Re-running it is the canonical "update my machine" path — everything
downstream is idempotent. Override the clone location with `BOOTSTRAP_DIR`
if you want it somewhere else.

### Profiles

The bootstrap has two profiles, selected via `BOOTSTRAP_PROFILE`:

- `server` (default) — installs only the base `Brewfile`: CLI tools plus the
  apps every machine gets, like Chrome, Zed, Tailscale and Screens Connect
- `personal` — also installs `Brewfile.personal`, which adds the rest of the
  casks and the Mac App Store apps

```sh
BOOTSTRAP_PROFILE=personal /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/nanoxd/bootstrap/main/install)"
```

From an existing checkout, pass it to make the same way:
`BOOTSTRAP_PROFILE=personal make`.

To only run homebrew: `make brew` (honors `BOOTSTRAP_PROFILE`)

The bootstrap leaves system preferences alone. Apply them with `make macOS`.

### Development tools

After Homebrew and dotfiles are ready, bootstrap restores the Fish plugins
listed in the dotfiles with `make fish-plugins`, then runs `mise install` to install
Node from the global mise config. Homebrew may install another Node as a formula
dependency. The shell configuration gives mise's selected version precedence.

Codex CLI, Claude Code, and uv use their standalone installers, outside
Homebrew. Existing installations in `~/.local/bin` are kept. Claude Code updates
automatically. Update Codex with its [standalone installer](https://learn.chatgpt.com/docs/codex/cli)
and uv with `uv self update`.

T3 Code Nightly remains in the personal Brewfile for initial installation and
uses its own updater afterward. Rex Beta is installed manually through the
[official testing program](https://www.superlogical.com/rex/docs/installation).

### Agent preferences

After GitHub authentication, bootstrap clones or updates the private
`nanoxd/agent-config` repo into `~/dev/agent-config` and applies it. This links
shared instructions and merges portable preferences while preserving local
settings. Existing files are backed up by its installer. Override the checkout
location with `AGENT_CONFIG_DIR` or rerun this step with `make agent-config`.

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
brew bundle dump --force --file=./Brewfile
```

### Dotfiles

The `setup` script installs dotfiles from
[nanoxd/dotfiles](https://github.com/nanoxd/dotfiles) via
[dot](https://github.com/ubnt-intrepid/dot). Change `DOTFILES_REPO` in
`setup` to point at your own repo.

## Acknowledgments

This project is heavily inspired by the following projects:

* [@thoughtbot Laptop](https://github.com/thoughtbot/laptop)
