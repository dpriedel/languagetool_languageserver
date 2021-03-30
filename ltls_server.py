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
import urllib3

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

logging.basicConfig(filename="/tmp/pyltls.log", level=logging.DEBUG, filemode="w")


def _find_line_ends(content: str):
    results: list[int] = []
    loc: int = content.find('\n')
    while loc > -1:
        results.append(loc)
        loc = content.find('\n', loc + 1)

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

    col = offset - offsets[line - 1] if line > 0 else offset + 1

    return(line, col - 1)


class LanguageToolLanguageServer(LanguageServer):

    CONFIGURATION_SECTION = 'ltlsServer'

    def __init__(self):
        super().__init__()

        self.languagetool_: subprocess.Popen = None
        self.language_: str = None
        self.port_: str = None
        self.http_ = urllib3.PoolManager()

    def __del__(self):
        self.languagetool_.kill()
        outs, errs = self.languagetool_.communicate()

    def StartLanguageTool(self, args):
        try:
            # we need to capture stdout, stderr because the languagetool server
            # emits several messages and we don't want them to go to the LSP client.

            self.language_ = args.language_
            self.port_ = args.port_

            command_and_args: list[str] = [args.command_, "--http"]
            if args.port_ != 8081:
                command_and_args.append("-p")
                command_and_args.append(args.port_)
            if args.languageModel_:
                command_and_args.append("--languageModel")
                command_and_args.append(args.languageModel_)
            if args.word2vecModel_:
                command_and_args.append("--word2vecModel")
                command_and_args.append(args.word2vecModel_)

            self.languagetool_ = subprocess.Popen(command_and_args,
                                                  stdin=subprocess.PIPE,
                                                  stdout=subprocess.PIPE,
                                                  stderr=subprocess.PIPE
                                                  )
            time.sleep(2.0)         # we need to give some time for the server to start.
            # outs, errs = self.languagetool_.communicate()
        except Exception as e:
            self.show_message('Error ocurred: {}'.format(e))

        self.start_io()


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
@ltls_server.feature(TEXT_DOCUMENT_DID_SAVE, TextDocumentSaveRegistrationOptions(includeText=True))
async def did_save(server: LanguageToolLanguageServer, params: DidSaveTextDocumentParams):
    """Actions run on textDocument/didSave."""

    # when we registered this function we told the client that we want
    # the text when the file is saved.  If we don't get it we'll fall
    # back to reading the file.

    doc_content: str = ""
    if params.text:
        doc_content = params.text
    else:
        fname = urlparse(params.text_document.uri, scheme="file")
        with open(fname.path, mode='r', encoding='utf-8') as saved_file:
            doc_content = saved_file.read()

    payload = {'language': server.language_, 'text': doc_content}
    url = 'http://localhost:' + server.port_ + '/v2/check'

    try:
        req = server.http_.request('GET', url, fields=payload, retries=urllib3.Retry(connect=5, backoff_factor=0.3))
        _publish_diagnostics(server, params.text_document.uri, doc_content, json.loads(req.data.decode('utf-8')))
    except Exception as e:
        server.show_message('Error ocurred: {}'.format(e))


# TEXT_DOCUMENT_DID_OPEN
@ltls_server.feature(TEXT_DOCUMENT_DID_OPEN)
async def did_open(server: LanguageToolLanguageServer, params: DidOpenTextDocumentParams):
    """Actions run on textDocument/didOpen."""
    doc_content = params.text_document.text
    payload = {'language': server.language_, 'text': doc_content}
    url = 'http://localhost:' + server.port_ + '/v2/check'

    try:
        req = server.http_.request('GET', url, fields=payload, retries=urllib3.Retry(connect=5, backoff_factor=0.3))
        _publish_diagnostics(server, params.text_document.uri, doc_content, json.loads(req.data.decode('utf-8')))
    except Exception as e:
        server.show_message('Error ocurred: {}'.format(e))


def add_arguments(parser):
    parser.description = "LanguageTool language http server on local host."

    parser.add_argument(
        "-l", "--language", type=str, dest="language_", default="en",
        help="Which language to use. Default is 'en'. Use 'en-US' for spell checking."
    )
    parser.add_argument(
        "-c", "--command", type=str, dest="command_", default="/usr/bin/languagetool",
        help="command to run language tool. Default is '/usr/bin/languagetool'."
    )
    parser.add_argument(
        "--languageModel", type=str, dest="languageModel_", default="",
        help="Optional directory containing 'n-grams'."
    )
    parser.add_argument(
        "--word2vecModel", type=str, dest="word2vecModel_", default="",
        help="Optional directory containing word2vec neural net data."
    )
    parser.add_argument(
        "-p", "--port", type=str, dest="port_", default="8081",
        help="Use this port for LanguageTool. Default is 8081. "
    )


def main():
    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    ltls_server.StartLanguageTool(args)


if __name__ == '__main__':
    main()
