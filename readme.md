# Bootstrap

Automating Mac configuration to be as reproducible as possible.

## Usage

On a fresh Mac, run:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/nanoxd/bootstrap/main/install)"
```

The `install` script takes care of Xcode Command Line Tools, clones (or
updates) this repo into `~/dev/bootstrap`, and then runs `make install`.
Re-running it is the canonical "update my machine" path — everything
downstream is idempotent. Override the clone location with `BOOTSTRAP_DIR`
if you want it somewhere else.

To only run homebrew: `make brew`

## Customization

The scripts as is favor my needs. To avoid installing packages you don't need,
I'd recommend dumping out your own configurations on your existing PC.

### Brew

`brew bundle` ships with Homebrew and reads dependencies from a `Brewfile`.
To snapshot your current setup:

```sh
brew bundle dump --file=./Brewfile
```

### Dotfiles

The `setup` script installs dotfiles from
[nanoxd/dotfiles](https://github.com/nanoxd/dotfiles) via
[dot](https://github.com/ubnt-intrepid/dot). Edit the `dot init` call in
`setup` to point at your own repo.

## Acknowledgments

This project is heavily inspired by the following projects:

* [@thoughtbot Laptop](https://github.com/thoughtbot/laptop)
