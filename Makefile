install:
	./setup

atom:
	apm install --packages-file ./Atomfile

brew:
	brew bundle --verbose --file=./Brewfile

defaults:
	./osx-defaults

go:
	./Gofile
