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
import asyncio
import json
import subprocess
import requests

import time

from urllib.parse import urlparse

from pygls.features import (TEXT_DOCUMENT_DID_SAVE,
                            TEXT_DOCUMENT_DID_CLOSE, TEXT_DOCUMENT_DID_OPEN)
from pygls.server import LanguageServer
from pygls.types import (ConfigurationItem, ConfigurationParams, Diagnostic,
                         DiagnosticSeverity, TextDocumentSaveRegistrationOptions,
                         DidSaveTextDocumentParams,
                         DidCloseTextDocumentParams, DidOpenTextDocumentParams,
                         MessageType, Position, Range, Registration, 
                         RegistrationParams, Unregistration,
                         UnregistrationParams)


class LanguageToolLanguageServer(LanguageServer):

    CONFIGURATION_SECTION = 'ltlsServer'

    def __init__(self):
        super().__init__()

        self.languagetool = None
        try:
            # we need to capture stdout, stderr because the languagetool server
            # emits several messages and we don't want them to go to the LSP client.

            self.languagetool = subprocess.Popen(["/usr/bin/languagetool", "--http"],
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


def _find_line_ends(content: str):
    """ make a list of line end offsets to be used when converting
        an offset into line and column."""

    results: list[int] = []

    loc = -1
    while True:
        loc = content.find('\n', loc + 1)
        if loc > -1:
            results.append(loc)
        else:
            break

    return results


def _convert_offset_to_line_col(offsets: list[int], offset: int) -> tuple[int, int]:
    """ just as it says, translate a zero-based offset to a line and column."""

    line: int = 0
    col: int = 0

    try:
        while (yyy := offsets[line]) < offset:
            line += 1
    except IndexError as e:
        pass

    if line > 0:
        col = offset - offsets[line - 1]
    else:
        col = offset + 1

    return(line, col - 1)


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
                            start=Position(line, col),
                            end=Position(line, col + int(error["length"]))
                         ),
                message=error["message"] + ' ' + error["rule"]["id"],
                severity=DiagnosticSeverity.Error,
                source="ltls"
             )
        diagnostics.append(d)
    if diagnostics:
        server.publish_diagnostics(uri, diagnostics)


# TEXT_DOCUMENT_DID_SAVE
@ltls_server.feature(TEXT_DOCUMENT_DID_SAVE)
async def did_save(server: LanguageToolLanguageServer, params: DidSaveTextDocumentParams):
    """Actions run on textDocument/didSave."""
    xxx = urlparse(params.textDocument.uri, scheme="file")

    doc_content = open(xxx.path, mode='r', encoding='utf-8').read()
    payload = {'language': 'en-US', 'text': doc_content}

    try:
        r = requests.get(r'http://localhost:8081/v2/check', params=payload)
        results = r.json()
        _publish_diagnostics(server, params.textDocument.uri, doc_content, results)
    except Exception as e:
        server.show_message('Error ocurred: {}'.format(e))


# TEXT_DOCUMENT_DID_OPEN
@ltls_server.feature(TEXT_DOCUMENT_DID_OPEN)
async def did_open(server: LanguageToolLanguageServer, params: DidOpenTextDocumentParams):
    """Actions run on textDocument/didOpen."""
    doc_content = params.textDocument.text
    payload = {'language': 'en-US', 'text': doc_content}

    try:
        r = requests.get(r'http://localhost:8081/v2/check', params=payload)
        results = r.json()
        _publish_diagnostics(server, params.textDocument.uri, doc_content, results)
    except Exception as e:
        server.show_message('Error ocurred: {}'.format(e))
