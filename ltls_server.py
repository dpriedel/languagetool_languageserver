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
# import uuid
import json

from pygls.features import (TEXT_DOCUMENT_DID_CHANGE, TEXT_DOCUMENT_DID_SAVE,
                            TEXT_DOCUMENT_DID_CLOSE, TEXT_DOCUMENT_DID_OPEN)
from pygls.server import LanguageServer
from pygls.types import (ConfigurationItem, ConfigurationParams, Diagnostic,
                         DiagnosticSeverity, TextDocumentSaveRegistrationOptions,
                         DidChangeTextDocumentParams, DidSaveTextDocumentParams,
                         DidCloseTextDocumentParams, DidOpenTextDocumentParams,
                         MessageType, Position, Range, Registration,
                         RegistrationParams, Unregistration,
                         UnregistrationParams)


class LanguageToolLanguageServer(LanguageServer):
    CMD_SHOW_CONFIGURATION_ASYNC = 'showConfigurationAsync'
    CMD_SHOW_CONFIGURATION_CALLBACK = 'showConfigurationCallback'
    CMD_SHOW_CONFIGURATION_THREAD = 'showConfigurationThread'

    CONFIGURATION_SECTION = 'ltlsServer'

    def __init__(self):
        super().__init__()

        self.languagetool = None
        try:
            self.languagetool = subprocess.Popen(["/usr/bin/languagetool", "--http"],
                                                 stdin=subprocess.PIPE,
                                                 stdout=subprocess.PIPE,
                                                 stderr=subprocess.PIPE
                                                 )
            time.sleep(3.0)         # we need to give some time for the server to start.
            # outs, errs = self.languagetool.communicate()
        except Exception as e:
            show_message('Error ocurred: {}'.format(e))

    def __del__(self):
        self.languagetool.kill()
        outs, errs = self.languagetool.communicate()


ltls_server = LanguageToolLanguageServer()


def _validate(ls, params):
    ls.show_message_log('Validating text...')

    text_doc = ls.workspace.get_document(params.textDocument.uri)

    source = text_doc.source
    diagnostics = _validate_text(source) if source else []

    ls.publish_diagnostics(text_doc.uri, diagnostics)


def _validate_text(source):
    """Validates text file."""
    diagnostics = []

    # try:
    #     json.loads(source)
    # except JSONDecodeError as err:
    #     msg = err.msg
    #     col = err.colno
    #     line = err.lineno

    #     d = Diagnostic(
    #         Range(
    #             Position(line - 1, col - 1),
    #             Position(line - 1, col)
    #         ),
    #         msg,
    #         source=type(ltls_server).__name__
    #     )

    #     diagnostics.append(d)

    return diagnostics


def _publish_diagnostics(server: LanguageToolLanguageServer, uri: str, results: dict):
    """Helper function to publish diagnostics for a file.
        results is already in json format from requests library."""
    # document = server.workspace.get_document(uri)
    # jedi_script = jedi_utils.script(server.project, document)
    # errors = jedi_script.get_syntax_errors()
    # diagnostics = [jedi_utils.lsp_diagnostic(error) for error in errors]
    diagnostics = []
    for error in results["matches"]:
        d = Diagnostic(
                range=Range(
                            start=Position(0, int(error["offset"])),
                            end=Position(0, int(error["offset"]) + int(error["length"]))
                         ),
                message=error["message"] + ' ' + error["rule"]["id"],
                severity=DiagnosticSeverity.Error,
                source="ltls"
             )
        diagnostics.append(d)
    if diagnostics:
        server.publish_diagnostics(uri, diagnostics)


# TEXT_DOCUMENT_DID_SAVE
@ltls_server.feature(TEXT_DOCUMENT_DID_SAVE, includeText=True)
async def did_save(server: LanguageToolLanguageServer, params: DidSaveTextDocumentParams):
    """Actions run on textDocument/didSave."""
    doc_content = params.text
    payload = {'language': 'en-US', 'text': doc_content}

    try:
        r = requests.get(r'http://localhost:8081/v2/check', params=payload)
        results = r.json()
        _publish_diagnostics(server, params.textDocument.uri, results)
    except Exception as e:
        server.show_message('Error ocurred: {}'.format(e))


# TEXT_DOCUMENT_DID_CHANGE
@ltls_server.feature(TEXT_DOCUMENT_DID_CHANGE)
def did_change(server: LanguageToolLanguageServer, params: DidChangeTextDocumentParams):
    """Actions run on textDocument/didChange."""
    # doc_content = params.contentChanges.
    # payload = {'language': 'en-US', 'text': doc_content}

    # try:
    #     r = requests.get(r'http://localhost:8081/v2/check', params=payload)
    #     results = r.json()
    #     _publish_diagnostics(server, params.textDocument.uri, results)
    # except Exception as e:
    #     server.show_message('Error ocurred: {}'.format(e))
    _publish_diagnostics(server, params.textDocument.uri, {})


# TEXT_DOCUMENT_DID_OPEN
@ltls_server.feature(TEXT_DOCUMENT_DID_OPEN)
async def did_open(server: LanguageToolLanguageServer, params: DidOpenTextDocumentParams):
    """Actions run on textDocument/didOpen."""
    doc_content = params.textDocument.text
    payload = {'language': 'en-US', 'text': doc_content}

    try:
        r = requests.get(r'http://localhost:8081/v2/check', params=payload)
        results = r.json()
        _publish_diagnostics(server, params.textDocument.uri, results)
    except Exception as e:
        server.show_message('Error ocurred: {}'.format(e))



@ltls_server.command(LanguageToolLanguageServer.CMD_SHOW_CONFIGURATION_ASYNC)
async def show_configuration_async(ls: LanguageToolLanguageServer, *args):
    """Gets exampleConfiguration from the client settings using coroutines."""
    try:
        config = await ls.get_configuration_async(ConfigurationParams([
            ConfigurationItem('', LanguageToolLanguageServer.CONFIGURATION_SECTION)
        ]))

        example_config = config[0].exampleConfiguration

        ls.show_message(
            'ltlsServer.exampleConfiguration value: {}'.format(example_config)
        )

    except Exception as e:
        ls.show_message_log('Error ocurred: {}'.format(e))


@ltls_server.command(LanguageToolLanguageServer.CMD_SHOW_CONFIGURATION_CALLBACK)
def show_configuration_callback(ls: LanguageToolLanguageServer, *args):
    """Gets exampleConfiguration from the client settings using callback."""
    def _config_callback(config):
        try:
            example_config = config[0].exampleConfiguration

            ls.show_message(
                'ltlsServer.exampleConfiguration value: {}'
                .format(example_config)
            )

        except Exception as e:
            ls.show_message_log('Error ocurred: {}'.format(e))

    ls.get_configuration(ConfigurationParams([
        ConfigurationItem('', LanguageToolLanguageServer.CONFIGURATION_SECTION)
    ]), _config_callback)


@ltls_server.thread()
@ltls_server.command(LanguageToolLanguageServer.CMD_SHOW_CONFIGURATION_THREAD)
def show_configuration_thread(ls: LanguageToolLanguageServer, *args):
    """Gets exampleConfiguration from the client settings using thread pool."""
    try:
        config = ls.get_configuration(ConfigurationParams([
            ConfigurationItem('', LanguageToolLanguageServer.CONFIGURATION_SECTION)
        ])).result(2)

        example_config = config[0].exampleConfiguration

        ls.show_message(
            'ltlsServer.exampleConfiguration value: {}'.format(example_config)
        )

    except Exception as e:
        ls.show_message_log('Error ocurred: {}'.format(e))

