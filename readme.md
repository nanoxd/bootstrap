# Bootstrap

Automating Mac configuration to be as reproducible as possible.

## Usage

1. `git clone https://github.com/nanoxd/bootstrap.git`
2. `cd bootstrap`
3. `make`

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
