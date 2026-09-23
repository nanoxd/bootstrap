# AGENTS.md

This file provides guidance to coding agents (Claude Code, Codex, and others) when working with code in this repository. `CLAUDE.md` is a symlink to this file.

## Repository Overview

This is a macOS system bootstrap automation tool that configures a fresh Mac installation with a complete development environment. The project automates installation of development tools, applications, and system preferences using Homebrew, Rust toolchain, and custom scripts.

## Key Commands

### Full System Bootstrap
On a fresh Mac, with nothing installed yet:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/nanoxd/bootstrap/main/install)"
```

From an existing checkout:
```bash
make                    # Run complete bootstrap process
make install           # Same as above - full installation
```

### Individual Components
```bash
make brew              # Install Homebrew packages from Brewfile
make macOS             # Apply macOS system preferences
make rust              # Install Rust packages from Cargofile
make git-signing       # Ensure SSH commit signing (key, agent, GitHub, git config)
```

### Testing Changes
```bash
./setup                # Run the main setup script directly
./macOS                # Test macOS preferences changes
./git-signing          # Safe to re-run; skips anything already done
brew bundle check      # Verify Brewfile dependencies
```

## Architecture & Key Components

### Core Scripts
- **install**: Fresh-machine entry point. Installs the Command Line Tools, clones this repo over HTTPS into `~/dev/bootstrap` (override with `BOOTSTRAP_DIR`), and runs `setup`. Invoke it with `bash -c "$(curl ...)"` rather than `curl | bash` so setup's prompts can read the terminal.
- **setup**: Main orchestrator script that runs the complete bootstrap process. Installs Homebrew, then Xcode before any formulas so they build against it instead of the Command Line Tools, then Rust, dotfiles, and fish. Clones dotfiles over HTTPS and links them before anything else can create `~/.config`, merging any existing directories into the repo first. Runs `git-signing` after dotfiles so `user.email` is set, then switches the dotfiles and bootstrap remotes to SSH. Never writes shell startup files, which the dotfiles own.
- **git-signing**: Idempotent SSH commit-signing setup. Logs in to GitHub with the scopes needed to manage keys, generates an ED25519 key if missing, loads it into the agent and Apple Keychain, registers it with GitHub as an authentication and signing key, writes `~/.ssh/allowed_signers`, and configures signing in `~/.gitconfig.local`. Leaves existing GPG keys untouched.
- **macOS**: Applies extensive macOS system preferences including Trackpad, Finder, Dock, and application-specific settings.

### Configuration Files
- **Brewfile**: Homebrew package definitions including CLI tools, GUI applications, and Mac App Store apps. Uses tap/brew/cask/mas syntax.
- **Cargofile**: Rust tools to install via cargo. Each line is a package name passed to `cargo install`. Only for crates Homebrew has no formula for, so a fresh bootstrap doesn't compile from source.
- **Makefile**: Build automation defining installation targets and dependencies.

### Security & Authentication
- Generates ED25519 SSH keys, commented with the git email when available
- Requests the GitHub token scopes needed to manage SSH keys (`admin:public_key`, `admin:ssh_signing_key`)
- Sets up SSH commit signing through Git and GitHub
- Writes signing preferences to `~/.gitconfig.local` and never touches `~/.gitconfig`, which dotfiles own and which includes the local file

## Development Guidelines

### Adding New Packages
- **Homebrew packages**: Add to appropriate section in `Brewfile` (tap, brew, cask, or mas). Entries from a non-Homebrew tap use the full `user/tap/name` and `trusted: true`, since Homebrew 7 refuses to load untrusted taps.
- **Rust tools**: Prefer a Homebrew formula in `Brewfile`. Add to `Cargofile` only if `brew info <name>` finds nothing.
- **Other binaries**: Add install logic directly in `setup`

### Testing Changes
Always test scripts in isolation before running full bootstrap:
1. Test individual make targets rather than full installation
2. Comment out irreversible operations when testing
3. Use `brew bundle check` to validate Brewfile syntax

### Script Conventions
- Preserve idempotency - scripts should be safe to run multiple times
- Use `set -e` for fail-fast behavior in shell scripts
- Target `/bin/bash` (bash 3.2 on macOS): no associative arrays, no `+=` on arrays under `set -u`
