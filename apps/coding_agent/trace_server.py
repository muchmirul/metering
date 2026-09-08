"""Explicit, finite-lived loopback viewer service. No worker or assay endpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import selectors
import shutil
import subprocess
import sys
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from apps._support.process import kill_process_tree
from apps._support.wire import canonical_json
from apps.coding_agent.operator_view import OperatorViewError
from apps.coding_agent.trace_view import TraceSnapshot

ROOT = Path(__file__).resolve().parents[2]
UI = Path(__file__).with_name("trace_ui")
MAX_RESPONSE = 16 * 1024 * 1024
IDLE_SECONDS = 15 * 60
LIFETIME_SECONDS = 4 * 60 * 60
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


def assets_ready() -> None:
    try:
        digest = hashlib.sha256()
        for name in [
            "package-lock.json",
            "build.mjs",
            "tsconfig.json",
            "index.html",
            "style.css",
            *[f"src/{path.name}" for path in sorted((UI / "src").iterdir())],
        ]:
            digest.update(name.encode())
            digest.update((UI / name).read_bytes())
        if (UI / "dist/source.sha256").read_text().strip() != digest.hexdigest():
            raise ValueError("stale build")
        for name, _mime in ASSETS.values():
            path = UI / "dist" / name
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size > 4 * 1024 * 1024
            ):
                raise ValueError("invalid asset")
    except (OSError, ValueError) as exc:
        raise OperatorViewError(
            "Trace viewer assets are missing/stale. Run: npm ci --prefix apps/coding_agent/trace_ui && npm run build --prefix apps/coding_agent/trace_ui"
        ) from exc


class TraceServer(HTTPServer):
    def __init__(self, runs: Path, selector: str, *, assets: Path | None = None):
        snapshot = TraceSnapshot(runs, selector)
        self.runs, self.selector = runs, selector
        self.snapshots: OrderedDict[str, TraceSnapshot] = OrderedDict(
            [(snapshot.snapshot_id, snapshot)]
        )
        self.current = snapshot.snapshot_id
        self.token = secrets.token_urlsafe(32)
        self.assets = assets or UI / "dist"
        self.started = self.last_access = time.monotonic()
        super().__init__(("127.0.0.1", 0), TraceHandler)
        self.timeout = 1
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(3)
        return connection, address

    @property
    def url(self) -> str:
        return self.origin + "/#token=" + self.token

    def snapshot(self, parameters: dict[str, str]) -> TraceSnapshot:
        if parameters.get("refresh") == "1":
            snapshot = TraceSnapshot(self.runs, self.selector)
            self.current = snapshot.snapshot_id
            self.snapshots[self.current] = snapshot
            self.snapshots.move_to_end(self.current)
            while len(self.snapshots) > 2:
                self.snapshots.popitem(last=False)
        identity = parameters.get("snapshot", self.current)
        if identity not in self.snapshots:
            raise OperatorViewError(
                "snapshot expired; refresh the graph before inspecting more evidence"
            )
        return self.snapshots[identity]

    def run_until_idle(
        self, *, idle: float = IDLE_SECONDS, lifetime: float = LIFETIME_SECONDS
    ) -> None:
        try:
            while (
                time.monotonic() - self.last_access < idle
                and time.monotonic() - self.started < lifetime
            ):
                self.handle_request()
        finally:
            self.server_close()


class TraceHandler(BaseHTTPRequestHandler):
    server: TraceServer
    protocol_version = "HTTP/1.0"

    def log_message(self, _format: str, *args: object) -> None:
        pass  # No token, source path, query, or candidate text in request logs.

    def respond(
        self,
        status: int,
        data: bytes,
        mime: str = "application/json",
        filename: str | None = None,
    ) -> None:
        if len(data) > MAX_RESPONSE:
            status, data, mime = (
                413,
                b'{"error":"response exceeds viewer bound"}',
                "application/json",
            )
        self.send_response(status)
        for key, value in {
            "Content-Type": mime,
            "Content-Length": str(len(data)),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Connection": "close",
            "Cross-Origin-Resource-Policy": "same-origin",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        }.items():
            self.send_header(key, value)
        if filename:
            self.send_header(
                "Content-Disposition", f'attachment; filename="{filename}"'
            )
        self.end_headers()
        self.close_connection = True
        self.wfile.write(data)

    def do_POST(self) -> None:
        self.respond(405, b'{"error":"viewer has no mutation endpoints"}')

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST
    do_OPTIONS = do_POST

    def do_GET(self) -> None:
        try:
            if (
                any(
                    len(self.headers.get_all(name, [])) > 1
                    for name in ("Host", "Origin", "Authorization")
                )
                or self.headers.get("Host")
                != self.server.origin.removeprefix("http://")
                or self.headers.get("Origin") not in {None, self.server.origin}
                or self.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"}
            ):
                self.respond(403, b'{"error":"cross-origin viewer request rejected"}')
                return
            if (
                len(self.path) > 8192
                or self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Length") not in {None, "0"}
            ):
                self.respond(400, b'{"error":"invalid viewer request"}')
                return
            url = urlsplit(self.path)
            if url.scheme or url.netloc:
                raise OperatorViewError("absolute request targets are not accepted")
            if url.path in ASSETS and not url.query:
                name, mime = ASSETS[url.path]
                path = self.server.assets / name
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or path.stat().st_size > 4 * 1024 * 1024
                ):
                    raise OperatorViewError("viewer asset is absent or unsafe")
                self.respond(200, path.read_bytes(), mime)
                return
            authorization = self.headers.get("Authorization", "")
            if not hmac.compare_digest(authorization, "Bearer " + self.server.token):
                self.respond(403, b'{"error":"missing or invalid viewer capability"}')
                return
            routes = {
                "/api/graph": {"snapshot", "refresh"},
                "/api/report": {"snapshot", "kind", "candidate", "offset"},
                "/api/loops": {"snapshot", "kind"},
                "/api/loop": {"snapshot", "kind", "label", "offset"},
                "/api/files": {
                    "snapshot",
                    "kind",
                    "candidate",
                    "offset",
                    "changed",
                    "base",
                },
                "/api/content": {"snapshot", "kind", "candidate", "path", "offset"},
                "/api/file": {"snapshot", "kind", "candidate", "path", "base"},
                "/api/blob": {"snapshot", "kind", "candidate", "path"},
                "/api/diff": {
                    "snapshot",
                    "kind",
                    "candidate",
                    "path",
                    "base",
                    "offset",
                },
                "/api/renames": {"snapshot", "kind", "candidate", "base"},
                "/api/file-history": {"snapshot", "kind", "path"},
                "/api/export": {"snapshot", "format"},
            }
            if url.path not in routes:
                self.respond(404, b'{"error":"unknown viewer route"}')
                return
            raw = parse_qs(url.query, keep_blank_values=True, max_num_fields=12)
            if set(raw) - routes[url.path] or any(
                len(value) != 1 for value in raw.values()
            ):
                raise OperatorViewError("unknown or duplicate viewer query parameter")
            parameters = {key: values[0] for key, values in raw.items()}
            for flag in ("changed", "refresh"):
                if flag in parameters and parameters[flag] not in {"0", "1"}:
                    raise OperatorViewError("viewer flags must be 0 or 1")
            offset = int(parameters.get("offset", "0"))
            if not 0 <= offset <= 1_000_000:
                raise OperatorViewError("viewer offset is outside its bound")
            snapshot = self.server.snapshot(parameters)
            kind, identity = parameters.get("kind", ""), parameters.get("candidate", "")
            self.server.last_access = time.monotonic()
            if url.path == "/api/graph":
                result = snapshot.graph()
            elif url.path == "/api/export":
                if parameters.get("format") == "csv":
                    self.respond(
                        200,
                        snapshot.csv(),
                        "text/csv; charset=utf-8",
                        "agentvolve-candidates.csv",
                    )
                    return
                if parameters.get("format") != "json":
                    raise OperatorViewError("export format must be json or csv")
                self.respond(
                    200,
                    canonical_json(snapshot.graph()).encode(),
                    "application/json",
                    "agentvolve-snapshot.json",
                )
                return
            elif url.path == "/api/report":
                result = snapshot.report(kind, identity, offset)
            elif url.path == "/api/loops":
                result = snapshot.loops(kind)
            elif url.path == "/api/loop":
                result = snapshot.loop(kind, parameters.get("label", ""), offset)
            elif url.path == "/api/file-history":
                result = snapshot.file_history(kind, parameters.get("path", ""))
            else:
                snapshot.node(kind, identity)
                files = snapshot.files[kind]
                base = parameters.get("base") or None
                if base:
                    snapshot.node(kind, base)
                key = parameters.get("path", "")
                if url.path == "/api/files":
                    result = snapshot.envelope(
                        files.files(
                            identity,
                            offset,
                            changed=parameters.get("changed") == "1",
                            base=base,
                        )
                    )
                elif url.path == "/api/file":
                    result = snapshot.envelope(files.change(identity, key, base))
                elif url.path == "/api/content":
                    result = snapshot.envelope(files.content(identity, key, offset))
                elif url.path == "/api/diff":
                    result = snapshot.envelope(files.diff(identity, key, base, offset))
                elif url.path == "/api/renames":
                    result = snapshot.envelope({"items": files.renames(identity, base)})
                elif url.path == "/api/blob":
                    self.respond(
                        200,
                        files.blob(identity, key),
                        "application/octet-stream",
                        "candidate-file.bin",
                    )
                    return
                else:
                    raise OperatorViewError("unimplemented file inspection route")
            self.respond(200, canonical_json(result).encode("ascii"))
        except (OperatorViewError, ValueError, TypeError, OSError) as exc:
            try:
                self.respond(400, canonical_json({"error": str(exc)}).encode("ascii"))
            except (OSError, BrokenPipeError):
                pass


def launch(runs: str, selector: str) -> dict:
    assets_ready()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "apps.coding_agent.trace_server",
            "serve",
            runs,
            selector,
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    assert process.stdout is not None
    try:
        data = bytearray()
        deadline = time.monotonic() + 30
        with selectors.DefaultSelector() as selector_:
            selector_.register(process.stdout, selectors.EVENT_READ)
            while b"\n" not in data:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector_.select(remaining):
                    raise OperatorViewError("trace viewer launch timed out")
                chunk = os.read(process.stdout.fileno(), 4096 - len(data))
                if not chunk or len(data) + len(chunk) >= 4096:
                    raise OperatorViewError(
                        "trace viewer did not return a bounded readiness record"
                    )
                data.extend(chunk)
        result = json.loads(data)
        if result.get("view_schema") != "agentvolve-trace-launch-v1":
            raise OperatorViewError("invalid trace viewer readiness record")
        return result
    except BaseException:
        kill_process_tree(process)
        raise
    finally:
        process.stdout.close()


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        open_browser = (
            len(arguments) == 4
            and arguments[3] == "--open"
            and arguments[0] == "launch"
        )
        if (len(arguments) != 3 and not open_browser) or arguments[0] not in {
            "launch",
            "serve",
        }:
            raise OperatorViewError(
                "usage: trace_server launch|serve RUNS RUN_NAME [--open (launch only)]"
            )
        if arguments[0] == "launch":
            result = launch(arguments[1], arguments[2])
            result["browser_open_requested"] = False
            if open_browser:
                opener = shutil.which(
                    "open" if sys.platform == "darwin" else "xdg-open"
                )
                if opener:
                    try:
                        subprocess.Popen(
                            [opener, result["url"]],
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True,
                        )
                        result["browser_open_requested"] = True
                    except OSError:
                        pass  # The capability URL remains available for manual opening.
            print(canonical_json(result))
        else:
            assets_ready()
            server = TraceServer(Path(arguments[1]), arguments[2])
            print(
                canonical_json(
                    {
                        "view_schema": "agentvolve-trace-launch-v1",
                        "authority": "projection-only",
                        "url": server.url,
                        "pid": os.getpid(),
                        "idle_seconds": IDLE_SECONDS,
                        "lifetime_seconds": LIFETIME_SECONDS,
                    }
                ),
                flush=True,
            )
            server.run_until_idle()
    except (OperatorViewError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
