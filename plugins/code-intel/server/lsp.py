"""Minimal JSON-RPC/LSP client for one long-lived ``basedpyright-langserver``.

One process per MCP server, shared by every tool.  Only stdin writes are
serialised, so a slow warm-up query never queues a later definition call
behind it.  The reader thread fails every pending request when the child dies,
which is what lets ``core`` restart it instead of hanging.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse


class LspError(Exception):
    """A language-server failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


def path_to_uri(path: str | Path) -> str:
    return Path(path).resolve().as_uri()


def uri_to_path(uri: str) -> Path:
    parts = urlparse(uri)
    path = unquote(parts.path)
    if parts.netloc:
        path = f"//{parts.netloc}{path}"
    if sys.platform == "win32" and path[:1] == "/" and path[2:3] == ":":
        path = path[1:]
    return Path(path)


class LspClient:
    def __init__(self, root: str | Path, command: list[str], log_path: Path | None = None) -> None:
        self.root = Path(root).resolve()
        self.command = list(command)
        self.log_path = log_path
        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()          # stdin writes + pending map
        self._pending: dict[int, Future] = {}
        self._next_id = 0
        self._closed = False
        self._reader: threading.Thread | None = None
        self._stderr_fh = None
        self.server_info: dict = {}
        self.diagnostics_handler: Callable[[str, list], None] | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self, timeout: float = 60.0) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        self._closed = False
        kwargs: dict = {"cwd": str(self.root), "stdin": subprocess.PIPE,
                        "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL}
        if self.log_path is not None:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                if self.log_path.exists() and self.log_path.stat().st_size > 5_000_000:
                    self.log_path.unlink()
                self._stderr_fh = self.log_path.open("ab")
                kwargs["stderr"] = self._stderr_fh
            except OSError:
                self._stderr_fh = None
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.proc = subprocess.Popen(self.command, **kwargs)
        except OSError as exc:
            raise LspError("lsp_missing", f"cannot start {self.command[0]!r}: {exc}") from exc
        self._reader = threading.Thread(target=self._read_loop, name="code-intel-lsp-reader", daemon=True)
        self._reader.start()
        init = self.request("initialize", {
            "processId": None,
            "clientInfo": {"name": "code-intel", "version": "0.1.0"},
            "rootUri": path_to_uri(self.root),
            "rootPath": str(self.root),
            "workspaceFolders": [{"uri": path_to_uri(self.root), "name": self.root.name}],
            "capabilities": {
                "workspace": {"symbol": {}, "configuration": True, "workspaceFolders": True},
                "textDocument": {"definition": {}, "references": {}, "documentSymbol": {},
                                 "hover": {"contentFormat": ["markdown", "plaintext"]},
                                 "publishDiagnostics": {}},
                "window": {"workDoneProgress": False},
            },
            "initializationOptions": {"diagnosticMode": "openFilesOnly"},
        }, timeout=timeout)
        self.server_info = (init or {}).get("serverInfo", {}) if isinstance(init, dict) else {}
        self.notify("initialized", {})

    def stop(self) -> None:
        self._closed = True
        proc = self.proc
        self.proc = None
        if proc is not None and proc.poll() is None:
            # Speak the LSP lifecycle instead of TerminateProcess: basedpyright's node child
            # outlives the python launcher when the launcher is killed, leaking ~600 MB per
            # restart (measured: three orphans after a handful of test runs).  Closing stdin
            # afterwards gives node the EOF it also exits on, in case it never sees `exit`.
            try:
                if proc.stdin is not None:
                    for message in ({"id": 0, "method": "shutdown", "params": None},
                                    {"method": "exit", "params": None}):
                        body = json.dumps({"jsonrpc": "2.0", **message}).encode("utf-8")
                        proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
                        proc.stdin.write(body)
                    proc.stdin.flush()
                    proc.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
        self._fail_pending(LspError("lsp_closed", "language server stopped"))

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None and not self._closed

    def pid(self) -> int | None:
        return self.proc.pid if self.proc is not None else None

    # ------------------------------------------------------------------ transport
    def _write(self, message: dict) -> None:
        proc = self.proc
        if proc is None or proc.stdin is None:
            raise LspError("lsp_closed", "language server is not running")
        body = json.dumps(message).encode("utf-8")
        with self._lock:
            try:
                proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
                proc.stdin.write(body)
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                raise LspError("lsp_closed", f"language server stdin closed: {exc}") from exc

    def _read_message(self) -> dict | None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return None
        headers: dict[str, str] = {}
        while True:
            line = proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            key, _, value = line.partition(b":")
            headers[key.strip().lower().decode("latin-1")] = value.strip().decode("latin-1")
        try:
            size = int(headers.get("content-length", "0"))
        except ValueError:
            return None
        if size <= 0:
            return None
        body = proc.stdout.read(size)
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return None

    def _read_loop(self) -> None:
        while True:
            try:
                message = self._read_message()
            except (OSError, ValueError):
                message = None
            if message is None:
                break
            if "id" in message and "method" in message:
                self._answer_server_request(message)
            elif "id" in message:
                with self._lock:
                    future = self._pending.pop(message["id"], None)
                if future is not None and not future.done():
                    if "error" in message:
                        err = message["error"] or {}
                        future.set_exception(LspError(
                            "lsp_request_failed",
                            f"{err.get('message', 'language server error')} (code {err.get('code')})"))
                    else:
                        future.set_result(message.get("result"))
            elif message.get("method"):
                self._on_notification(message)
        self._fail_pending(LspError("lsp_died", "language server process exited"))

    def _answer_server_request(self, message: dict) -> None:
        # pyright asks for workspace/configuration and client/registerCapability;
        # answering null keeps it quiet instead of stalling on a reply that never comes.
        result = []
        if message.get("method") == "workspace/configuration":
            result = [None] * len((message.get("params") or {}).get("items") or [])
        try:
            self._write({"jsonrpc": "2.0", "id": message["id"], "result": result})
        except LspError:
            pass

    def _on_notification(self, message: dict) -> None:
        # publishDiagnostics is the only notification the tools use; core installs the handler.
        if message.get("method") == "textDocument/publishDiagnostics" and self.diagnostics_handler is not None:
            params = message.get("params") or {}
            self.diagnostics_handler(params.get("uri") or "", params.get("diagnostics") or [])

    def _fail_pending(self, exc: LspError) -> None:
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(exc)

    def request(self, method: str, params: dict, timeout: float = 30.0):
        future: Future = Future()
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            self._pending[request_id] = future
        try:
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        except LspError:
            with self._lock:
                self._pending.pop(request_id, None)
            raise
        try:
            return future.result(timeout=timeout)
        except FutureTimeout:
            with self._lock:
                self._pending.pop(request_id, None)
            try:
                self._write({"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": request_id}})
            except LspError:
                pass
            raise LspError("lsp_timeout", f"{method} did not answer within {timeout:.0f}s")

    def notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})
