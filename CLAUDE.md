# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a macOS system bootstrap automation tool that configures a fresh Mac installation with a complete development environment. The project automates installation of development tools, applications, and system preferences using Homebrew, Rust toolchain, and custom scripts.

## Key Commands

### Full System Bootstrap
```bash
make                    # Run complete bootstrap process
make install           # Same as above - full installation
```

### Individual Components
```bash
make brew              # Install Homebrew packages from Brewfile
make macOS             # Apply macOS system preferences
make rust              # Install Rust packages from Cargofile
make custom_bins       # Install custom binaries (mise, bun, deno)
```

### Testing Changes
```bash
./setup                # Run the main setup script directly
./macOS                # Test macOS preferences changes
brew bundle check      # Verify Brewfile dependencies
```

## Architecture & Key Components

### Core Scripts
- **setup**: Main orchestrator script that runs the complete bootstrap process. Handles SSH/GPG key generation, GitHub integration, and coordinates all installation steps.
- **macOS**: Applies extensive macOS system preferences including Trackpad, Finder, Dock, and application-specific settings.
- **custom_bins**: Installs binaries not available through Homebrew or Cargo (mise, bun, deno).
- **shared.sh**: Utility functions for colored output and logging used across all scripts.

### Configuration Files
- **Brewfile**: Homebrew package definitions including CLI tools, GUI applications, and Mac App Store apps. Uses tap/brew/cask/mas syntax.
- **Cargofile**: Rust tools to install via cargo. Each line is a package name passed to `cargo install`.
- **Makefile**: Build automation defining installation targets and dependencies.

### Multi-Architecture Support
The scripts automatically detect Apple Silicon vs Intel Macs and adjust Homebrew paths:
- Apple Silicon: `/opt/homebrew`
- Intel: `/usr/local`

### Security & Authentication
- Generates ED25519 SSH keys with user-provided email
- Sets up GPG keys for Git commit signing
- Configures Git with signing preferences
- Integrates with GitHub for key management

## Development Guidelines

### Adding New Packages
- **Homebrew packages**: Add to appropriate section in `Brewfile` (tap, brew, cask, or mas)
- **Rust tools**: Add package name to `Cargofile`
- **Other binaries**: Update `custom_bins` script with installation logic

### Testing Changes
Always test scripts in isolation before running full bootstrap:
1. Test individual make targets rather than full installation
2. Comment out irreversible operations when testing
3. Use `brew bundle check` to validate Brewfile syntax

### Script Conventions
- Use functions from `shared.sh` for consistent output formatting
- Check architecture with `uname -m` for Apple Silicon compatibility
- Preserve idempotency - scripts should be safe to run multiple times
- Use `set -e` for fail-fast behavior in shell scripts

## Known Issues
- GPG generation needs fixing (see TODO file)