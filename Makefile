install:
	./setup

atom:
	apm install --packages-file ./Atomfile

brew:
	brew bundle --file=./Brewfile

defaults:
	./osx-defaults
