# Bootstrap

Automating CPU configuration to be as reproducible as possible.

## Usage

1. `git clone https://github.com/nanoxd/bootstrap.git`
2. `cd bootstrap`
3. `make`

To only run homebrew or atom, `make brew` or `make atom` respectively

## Customization

The scripts as is favor my needs. To avoid installing packages you don't need, I'd recommend dumping out your own configurations on your existing PC.

### Atom

`apm` allows you to view what packages you have installed.

```sh
# Lists all packages with version number into an Atomfile
apm ls --bare > Atomfile

# OR: If you'd like to have only the package name
apm ls --bare | cut -d'@' -f1 > Atomfile
```

### Brew

[homebrew-bundle](https://github.com/Homebrew/homebrew-bundle) is a bundler for your `brew` dependencies. Installing it is as simple as `brew tap Homebrew/bundle`.

```sh
# Creates your Brewfile
brew bundle dump --file=./Brewfile
```