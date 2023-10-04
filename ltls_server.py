#!/usr/bin/python3.11

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
import glob
import json
import logging
import subprocess
import time
from urllib.parse import urlparse

import urllib3
from lsprotocol import types as lsp
# from pygls.capabilities import get_capability
# from pygls.protocol import LanguageServerProtocol, lsp_method
from pygls.server import LanguageServer

logging.basicConfig(filename="/tmp/pyltls.log", level=logging.DEBUG, filemode="w")

LANGTOOL_PATH = "/usr/share/java/languagetool/"
CLASS_PATH = None


def _find_line_ends(content: str):
    results: list[int] = []
    loc: int = content.find("\n")
    while loc > -1:
        results.append(loc)
        loc = content.find("\n", loc + 1)

    return results


def _convert_offset_to_line_col(offsets: list[int], offset: int) -> tuple[int, int]:
    """just as it says, translate a zero-based offset to a line and column."""

    line: int = 0
    col: int = 0

    try:
        while offsets[line] < offset:
            line += 1
    except IndexError:
        pass

    col = offset - offsets[line - 1] if line > 0 else offset + 1

    return (line, col - 1)


class LanguageToolLanguageServer(LanguageServer):
    CONFIGURATION_SECTION = "ltlsServer"

    def __init__(self, *args):
        super().__init__(*args)

        self.languagetool_: subprocess.Popen = None
        self.language_: str = None
        self.port_: str = None
        self.http_ = urllib3.PoolManager()

    def __del__(self):
        # just in case...
        self.ShutdownLanguageTool()

    def StillAlive(self):
        return self.languagetool_ is not None

    def StartLanguageTool(self, args):
        try:
            # we need to capture stdout, stderr because the languagetool server
            # emits several messages and we don't want them to go to the LSP client.

            # need to build our class path so we can call languagetool directly ourselves
            # instead of using the provided script.  Need to remove the intermediate process
            # so we can properly shutdown the server from Neovim's LSP code.

            jars = glob.glob(LANGTOOL_PATH + "*.jar")
            CLASS_PATH = "/usr/share/languagetool:" + ":".join(jars)

            self.language_ = args.language_
            self.port_ = args.port_

            command_and_args = [
                "java",
                "-cp",
                CLASS_PATH,
                "org.languagetool.server.HTTPServer",
            ]

            # command_and_args: list[str] = [args.command_, "--http"]
            if args.port_ != 8081:
                command_and_args.append("-p")
                command_and_args.append(args.port_)
            if args.languageModel_:
                command_and_args.append("--languageModel")
                command_and_args.append(args.languageModel_)
            if args.word2vecModel_:
                command_and_args.append("--word2vecModel")
                command_and_args.append(args.word2vecModel_)

            # print(command_and_args)
            self.languagetool_ = subprocess.Popen(
                command_and_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(2.0)  # we need to give some time for the server to start.
            # outs, errs = self.languagetool_.communicate()
        except Exception as e:
            self.show_message("Error ocurred: {}".format(e))

        self.start_io()

    def shutdown(self):
        self.ShutdownLanguageTool()

    def ShutdownLanguageTool(self):
        # logger = logging.getLogger()
        # logger.debug("got shutdown request.")
        if self.languagetool_:
            self.languagetool_.kill()
            outs, errs = self.languagetool_.communicate()
            self.languagetool_ = None
            # self.show_message("msg = " + outs + " errs = " + errs)


ltls_server = LanguageToolLanguageServer("ltlsServer", "0.9")


def _validate(server, params):
    # server.show_message_log("Validating text...")

    doc_content: str = ""
    if hasattr(params, "text") and params.text:
        doc_content = params.text
        server.show_message_log("Got text...")
    else:
        text_doc = server.workspace.get_text_document(params.text_document.uri)
        doc_content = text_doc.source

    diagnostics = _validate_text(server, doc_content) if doc_content else []
    server.publish_diagnostics(params.text_document.uri, diagnostics)


def _validate_text(server, doc_content):
    """Validates text file."""

    diagnostics = []

    payload = {"language": server.language_, "text": doc_content}
    url = "http://localhost:" + server.port_ + "/v2/check"

    try:
        req = server.http_.request(
            "GET",
            url,
            fields=payload,
            retries=urllib3.Retry(connect=5, backoff_factor=0.3),
        )

        results = json.loads(req.data.decode("utf-8"))

        offsets = _find_line_ends(doc_content)

        for error in results["matches"]:
            offset = int(error["offset"])
            line, col = _convert_offset_to_line_col(offsets, offset)
            d = lsp.Diagnostic(
                range=lsp.Range(
                    start=lsp.Position(line=line, character=col),
                    end=lsp.Position(line=line, character=col + int(error["length"])),
                ),
                message=error["message"] + " " + error["rule"]["id"],
                severity=lsp.DiagnosticSeverity.Error,
                source="ltls",
            )
            diagnostics.append(d)

    except Exception as e:
        server.show_message("Error ocurred: {}".format(e))

    return diagnostics


# @ltls_server.feature(lsp.shutdown)
# def shutdown():
#     """actions run on shutdown."""
#
#     # when we get here, we know we are really all done so it
#     # is safe to shutdown languagetool.
#
#     ltls_server.shutdownlanguagetool()
#     return


@ltls_server.feature(lsp.EXIT)
def exit():
    """Actions run on shutdown."""

    # when we get here, we know we are really all done so it
    # is safe to shutdown LanguageTool.

    if ltls_server.StillAlive() == True:
        ltls_server.ShutdownLanguageTool()


@ltls_server.feature(lsp.TEXT_DOCUMENT_DID_SAVE, lsp.SaveOptions(include_text=True))
async def did_save(
    server: LanguageToolLanguageServer, params: lsp.DidSaveTextDocumentParams
):
    """Actions run on textDocument/didSave."""
    server.show_message("Text Document Did Save")

    # when we registered this function we told the client that we want
    # the text when the file is saved.  If we don't get it we'll fall
    # back to reading the file.

    _validate(server, params)


@ltls_server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls, params: lsp.DidChangeTextDocumentParams):
    """Text document did change notification."""
    _validate(ls, params)


# TEXT_DOCUMENT_DID_OPEN
@ltls_server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
async def did_open(
    server: LanguageToolLanguageServer, params: lsp.DidOpenTextDocumentParams
):
    """Actions run on textDocument/didOpen."""

    server.show_message("Text Document Did Open")
    _validate(server, params)


def add_arguments(parser):
    parser.description = "LanguageTool language http server on local host."

    parser.add_argument(
        "-l",
        "--language",
        type=str,
        dest="language_",
        default="en",
        help="Which language to use. Default is 'en'. Use 'en-US' for spell checking.",
    )
    parser.add_argument(
        "-c",
        "--command",
        type=str,
        dest="command_",
        default="/usr/bin/languagetool",
        help="command to run language tool. Default is '/usr/bin/languagetool'.",
    )
    parser.add_argument(
        "--languageModel",
        type=str,
        dest="languageModel_",
        default="",
        help="Optional directory containing 'n-grams'.",
    )
    parser.add_argument(
        "--word2vecModel",
        type=str,
        dest="word2vecModel_",
        default="",
        help="Optional directory containing word2vec neural net data.",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=str,
        dest="port_",
        default="8081",
        help="Use this port for LanguageTool. Default is 8081. ",
    )


def main():
    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    ltls_server.StartLanguageTool(args)


if __name__ == "__main__":
    main()
