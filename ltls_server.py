#!/usr/local/python_dpr/bin/python

############################################################################
#                                                                          #
# Licensed under the Apache License, Version 2.0 (the "License")           #
# you may not use this file except in compliance with the License.         #
# You may obtain a copy of the License at                                  #
#                                                                          #
#     http: // www.apache.org/licenses/LICENSE-2.0                         #
#                                                                          #
# Unless required by applicable law or agreed to in writing, software      #
# distributed under the License is distributed on an "AS IS" BASIS,        #
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. #
# See the License for the specific language governing permissions and      #
# limitations under the License.                                           #
############################################################################
import argparse
import logging
import sys
import os
import asyncio
import json
import subprocess
import requests

import time

from urllib.parse import urlparse

from pygls.lsp.methods import (TEXT_DOCUMENT_DID_SAVE,
                               TEXT_DOCUMENT_DID_CLOSE, TEXT_DOCUMENT_DID_OPEN)
from pygls.lsp.types import (ConfigurationItem, ConfigurationParams, Diagnostic,
                             DiagnosticSeverity, TextDocumentSaveRegistrationOptions,
                             DidSaveTextDocumentParams,
                             DidCloseTextDocumentParams, DidOpenTextDocumentParams,
                             MessageType, Position, Range, Registration,
                             RegistrationParams, Unregistration,
                             UnregistrationParams)
from pygls.server import LanguageServer

logging.basicConfig(filename="/tmp/pyltls.log", level=logging.WARNING, filemode="w")


def _find_next_line_end(content: str):
    loc: int = content.find('\n')
    while loc > -1:
        yield loc
        loc = content.find('\n', loc + 1)


def _find_line_ends(content: str):
    """ make a list of line end offsets to be used when converting
        an offset into line and column."""

    results: list[int] = [loc for loc in _find_next_line_end(content)]
    return results


def _convert_offset_to_line_col(offsets: list[int], offset: int) -> tuple[int, int]:
    """ just as it says, translate a zero-based offset to a line and column."""

    line: int = 0
    col: int = 0

    try:
        while offsets[line] < offset:
            line += 1
    except IndexError as e:
        pass

    if line > 0:
        col = offset - offsets[line - 1]
    else:
        col = offset + 1

    return(line, col - 1)


class LanguageToolLanguageServer(LanguageServer):

    CONFIGURATION_SECTION = 'ltlsServer'

    def __init__(self):
        super().__init__()

        self.languagetool = None
        try:
            # we need to capture stdout, stderr because the languagetool server
            # emits several messages and we don't want them to go to the LSP client.

            self.languagetool = subprocess.Popen(["/usr/bin/languagetool", "--http",
                                                  # "--languageModel", "/util/langtool_ngrams",
                                                  "--word2vecModel", "/usr/share/word2vec/"],
                                                 stdin=subprocess.PIPE,
                                                 stdout=subprocess.PIPE,
                                                 stderr=subprocess.PIPE
                                                 )
            time.sleep(3.0)         # we need to give some time for the server to start.
            # outs, errs = self.languagetool.communicate()
        except Exception as e:
            self.show_message('Error ocurred: {}'.format(e))

    def __del__(self):
        self.languagetool.kill()
        outs, errs = self.languagetool.communicate()


ltls_server = LanguageToolLanguageServer()


def _publish_diagnostics(server: LanguageToolLanguageServer, uri: str, doc_content: str, results: dict):
    """Helper function to publish diagnostics for a file.
        results is already in json format from requests library."""

    offsets = _find_line_ends(doc_content)

    diagnostics = []
    for error in results["matches"]:
        offset = int(error["offset"])
        line, col = _convert_offset_to_line_col(offsets, offset)
        d = Diagnostic(
                range=Range(
                            start=Position(line=line, character=col),
                            end=Position(line=line, character=col + int(error["length"]))
                         ),
                message=error["message"] + ' ' + error["rule"]["id"],
                severity=DiagnosticSeverity.Error,
                source="ltls"
             )
        diagnostics.append(d)
    server.publish_diagnostics(uri, diagnostics)


# TEXT_DOCUMENT_DID_SAVE
@ltls_server.feature(TEXT_DOCUMENT_DID_SAVE)
async def did_save(server: LanguageToolLanguageServer, params: DidSaveTextDocumentParams):
    """Actions run on textDocument/didSave."""
    xxx = urlparse(params.text_document.uri, scheme="file")

    doc_content = open(xxx.path, mode='r', encoding='utf-8').read()
    payload = {'language': 'en', 'text': doc_content}

    try:
        r = requests.get(r'http://localhost:8081/v2/check', params=payload)
        results = r.json()
        _publish_diagnostics(server, params.text_document.uri, doc_content, results)
    except Exception as e:
        server.show_message('Error ocurred: {}'.format(e))


# TEXT_DOCUMENT_DID_OPEN
@ltls_server.feature(TEXT_DOCUMENT_DID_OPEN)
async def did_open(server: LanguageToolLanguageServer, params: DidOpenTextDocumentParams):
    """Actions run on textDocument/didOpen."""
    doc_content = params.text_document.text
    payload = {'language': 'en', 'text': doc_content}

    try:
        r = requests.get(r'http://localhost:8081/v2/check', params=payload)
        results = r.json()
        _publish_diagnostics(server, params.text_document.uri, doc_content, results)
    except Exception as e:
        server.show_message('Error ocurred: {}'.format(e))


def add_arguments(parser):
    parser.description = "LanguageTool language server"

    parser.add_argument(
        "--tcp", action="store_true",
        help="Use TCP server instead of stdio"
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Bind to this address"
    )
    parser.add_argument(
        "--port", type=int, default=9020,
        help="Bind to this port"
    )


def main():
    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    if args.tcp:
        ltls_server.start_tcp(args.host, args.port)
    else:
        ltls_server.start_io()


if __name__ == '__main__':
    main()
