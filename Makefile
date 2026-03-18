install:
	./setup

brew:
	brew bundle --verbose --file=./Brewfile

macOS:
	./macOS

rust:
	./Cargofile
