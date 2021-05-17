#!/usr/bin/env sh

BUILD_DIR="$HOME/.cache/nvim"

if [ ! -d "$BUILD_DIR" ]; then
  mkdir -p "$BUILD_DIR"
fi

if [ ! -d "$BUILD_DIR/nlua/sumneko_lua" ]; then
  LUA_LSP_DIR="$BUILD_DIR/nlua/sumneko_lua"
  mkdir -p "$LUA_LSP_DIR"
  cd "$LUA_LSP_DIR"
  git clone https://github.com/sumneko/lua-language-server 
  cd lua-language-server

  git submodule update --init --recursive
  cd 3rd/luamake
  compile/install.sh
  cd ../..
  ./3rd/luamake/luamake rebuild
fi
