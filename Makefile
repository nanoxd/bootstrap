install:
	./setup

atom:
	apm install --packages-file ./Atomfile

brew:
	brew bundle --verbose --file=./Brewfile

defaults:
	./osx-defaults

go:
	cat ./Gofile | xargs go get

rust:
	./Cargofile

yarn:
	cat ./Yarnfile | xargs yarn global add
