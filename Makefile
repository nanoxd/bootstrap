.PHONY: install brew macOS rust

BOOTSTRAP_PROFILE ?= personal

install:
	./setup

brew:
	brew bundle --verbose --file=./Brewfile
ifeq ($(BOOTSTRAP_PROFILE),personal)
	brew bundle --verbose --file=./Brewfile.personal
endif

macOS:
	./macOS

rust:
	./Cargofile
