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

custom_bins:
	./custom_bins

gems:
	./Gemsfile
