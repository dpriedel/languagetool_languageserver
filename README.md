languagetool_languageserver

This is a very simple LSP server which runs the LanguageTool application in http mode.

It supports check on file open and file save.

The server is built using the pygls framework.

It works well enough for me to use it to edit my wife's novel-in-progress.

I use it via the coc-ltls extension also available in another of my repositories.

Version 2.0 is significantly refactored to use the updated pygls 1.1 framework.

I currently use this server primarily from Neovim and its built-in LSP client.

The server now supports DidChange events too.

