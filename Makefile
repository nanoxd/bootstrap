.PHONY: install brew macOS rust git-signing

BOOTSTRAP_PROFILE ?= personal

install:
	./setup

brew:
	brew bundle --verbose --file=./Brewfile
ifeq ($(BOOTSTRAP_PROFILE),personal)
	@# Personal apps shouldn't stop the bootstrap. mas fails when the App Store
	@# is signed out, and one broken cask shouldn't block fish, signing or Rust.
	brew bundle --verbose --file=./Brewfile.personal || \
		printf '\nSome personal apps failed to install. Sign in to the App Store if mas apps failed, then run make brew again.\n'
endif

macOS:
	./macOS

rust:
	./Cargofile

git-signing:
	./git-signing
