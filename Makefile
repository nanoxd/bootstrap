install:
	./setup

brew:
	brew bundle --verbose --file=./Brewfile

macOS:
	./macOS

go:
	cat ./Gofile | xargs go get

rust:
	./Cargofile

yarn:
	cat ./Yarnfile | xargs yarn global add

custom_bins:
	./custom_bins
