.PHONY: install brew skills fish-plugins agent-config macOS rust git-signing repos t3-ops sim-janitor sim-janitor-uninstall test

BOOTSTRAP_PROFILE ?= server

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

skills:
	skl profile set $(BOOTSTRAP_PROFILE)
	@# A skill that fails to fetch shouldn't stop the bootstrap. skl keeps
	@# whatever it already installed, so rerunning make skills picks up the rest.
	skl sync || \
		printf '\nSome skills failed to sync. Run make skills again once the problem is fixed.\n'

fish-plugins:
	./fish-plugins

agent-config:
	./agent-config

macOS:
	./macOS

rust:
	./Cargofile

git-signing:
	./git-signing

repos:
	./repos

t3-ops:
	@if [ -x "$(HOME)/dev/t3-ops/install.sh" ]; then "$(HOME)/dev/t3-ops/install.sh"; \
	else echo "No ~/dev/t3-ops checkout. Run make repos first."; fi

sim-janitor:
	./sim-janitor-install

sim-janitor-uninstall:
	./sim-janitor-install uninstall

test:
	/usr/bin/python3 -m unittest discover -s tests
