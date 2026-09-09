"""Bounded, read-only task input inspection. No source instruction is executed.

Git inputs are exact regular blobs, local inputs explicit regular UTF-8 files,
and web inputs public HTTP(S) documents. This is not a browser or a crawler.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import os
import re
import socket
import stat
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

from apps._support.wire import decode_json_object, write_document
from apps.coding_agent.inspection_git import git_bytes, object_digest
from apps.coding_agent.operator_view import OperatorViewError
from apps.coding_agent.task_context import MAX_CONTEXT_BYTES, MAX_SOURCE_BYTES, MAX_SOURCES
from apps.harness.workspace import normalized_path

MAX_DOWNLOAD_BYTES = 524_288


class TaskSourceError(ValueError):
    """An input cannot be read safely and completely within preparation bounds."""


def _git(repository: Path, *args: str) -> bytes:
    try:
        return git_bytes(repository, list(args), limit=MAX_SOURCE_BYTES, timeout=10, worktree=True)
    except OperatorViewError as exc:
        raise TaskSourceError("Cannot read the requested input from the pinned Git commit within inspection bounds") from exc


def _snapshot(uri: str, payload: bytes, representation: str = "utf-8") -> dict[str, str]:
    if len(uri) > 4096:
        raise TaskSourceError("Source attribution exceeds its URI bound; supply a shorter direct reference")
    if len(payload) > MAX_SOURCE_BYTES:
        raise TaskSourceError(f"Input exceeds {MAX_SOURCE_BYTES} bytes; provide a smaller relevant text source")
    try:
        content = payload.decode("utf-8")
    except UnicodeError as exc:
        raise TaskSourceError("Input is not UTF-8 text; export a text representation for review") from exc
    if "\0" in content:
        raise TaskSourceError("Binary input is unsupported; export a text representation for review")
    return {"uri": uri, "representation": representation, "sha256": hashlib.sha256(payload).hexdigest(), "content": content}


def git_snapshot(repository: Path, commit: str, path: str) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise TaskSourceError("Input inspection requires a full immutable Git commit")
    path = normalized_path(path, "task input")
    entries = _git(repository, "ls-tree", "-z", "--full-tree", commit, "--", f":(literal){path}").split(b"\0")
    entries = [entry for entry in entries if entry]
    if len(entries) != 1:
        raise TaskSourceError(f"Input is absent or ambiguous at the reviewed commit: {path}")
    metadata, actual_path = entries[0].split(b"\t", 1)
    mode, kind, blob = metadata.split(b" ")
    if mode not in (b"100644", b"100755") or kind != b"blob" or actual_path.decode("utf-8") != path:
        raise TaskSourceError(f"Input must be a regular Git file, not a symlink, directory or submodule: {path}")
    if int(_git(repository, "cat-file", "-s", blob.decode("ascii"))) > MAX_SOURCE_BYTES:
        raise TaskSourceError(f"Input exceeds {MAX_SOURCE_BYTES} bytes: {path}; narrow the input")
    payload = _git(repository, "cat-file", "blob", blob.decode("ascii"))
    if object_digest("blob", payload, blob.decode("ascii")) != blob.decode("ascii"):
        raise TaskSourceError("Git input blob does not match its immutable object identity")
    uri = repository.absolute().as_uri() + "/" + quote(path, safe="/") + "?git_commit=" + commit
    return _snapshot(uri, payload)


def local_snapshot(path: Path) -> dict[str, str]:
    if not path.is_absolute() or path.resolve() != path:
        raise TaskSourceError("Local input must be an explicit absolute path without symlink ancestors")
    if os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW"):
        raise TaskSourceError("Safe local file inspection is unavailable on this platform; use committed Git input")
    # Walk pinned directory descriptors: a parent swapped for a symlink after
    # resolve() must not turn an approved path into a read of another host file.
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(path.anchor, directory_flags)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(path.name or ".", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_SOURCE_BYTES:
            raise TaskSourceError("Local input must be a bounded regular file; directories/devices are not read")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(MAX_SOURCE_BYTES + 1)
        after = os.fstat(descriptor)
        if any(getattr(metadata, field) != getattr(after, field) for field in ("st_size", "st_mtime_ns", "st_ctime_ns")):
            raise TaskSourceError("Local input changed while being inspected; request a fresh review")
    finally:
        os.close(descriptor)
    return _snapshot(path.as_uri(), payload)


class _HTMLText(HTMLParser):
    """Inert text, including inline script/style data; never run a browser.

    Tag attributes, images, external scripts and dynamic DOM are not represented.
    The explicit representation label prevents claiming this is the full HTML.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _public_endpoint(url: str) -> tuple[str, str, int, str]:
    if len(url) > 4096 or any(ord(c) < 33 for c in url) or "\\" in url:
        raise TaskSourceError("Source URL contains unsupported characters or exceeds its bound")
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise TaskSourceError("Source URL must be public HTTP(S), without credentials")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port != (443 if parsed.scheme == "https" else 80):
        raise TaskSourceError("Source URLs support only standard HTTP(S) ports")
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    ips = [address[4][0] for address in addresses]
    if not ips:
        raise TaskSourceError("Source URL has no address")
    for address in ips:
        ip = ipaddress.ip_address(address)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise TaskSourceError("Private, loopback, reserved and link-local source URLs are not permitted")
    return parsed.scheme, parsed.hostname, port, ips[0]


def _connection(scheme: str, host: str, port: int, ip: str, timeout: float) -> http.client.HTTPConnection:
    connection = (http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection)(host, port, timeout=timeout)
    # Pin the validated address: no second hostname lookup, proxy, cookies or auth.
    # HTTPSConnection still uses the original hostname for SNI/certificate checks.
    connection._create_connection = lambda _address, timeout, source_address=None: socket.create_connection(  # type: ignore[attr-defined]
        (ip, port), timeout, source_address,
    )
    return connection


def url_snapshot(url: str) -> dict[str, str]:
    original, current = url, url
    deadline = time.monotonic() + 20
    for redirects in range(4):
        scheme, host, port, ip = _public_endpoint(current)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TaskSourceError("Source download timed out; no workflow started")
        connection = _connection(scheme, host, port, ip, min(5, remaining))
        try:
            parsed = urlsplit(current)
            target = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
            connection.request("GET", target, headers={"Accept-Encoding": "identity", "User-Agent": "Agentvolve-input-review/1"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or redirects == 3:
                    raise TaskSourceError("Source URL redirect is absent or exceeds three hops")
                current = urljoin(current, location)
                if scheme == "https" and urlsplit(current).scheme != "https":
                    raise TaskSourceError("Source URL cannot redirect from HTTPS to an insecure scheme")
                continue
            if response.status != 200:
                raise TaskSourceError(f"Source URL returned HTTP {response.status}; supply an accessible document")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise TaskSourceError("Compressed source responses are unsupported; supply a plain document")
            media = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if not (media.startswith("text/") or media in ("application/json", "application/javascript", "application/xml")):
                raise TaskSourceError("Source URL is not a supported text document; browsers, images and downloads are not executed")
            chunks: list[bytes] = []
            size = 0
            while True:
                if time.monotonic() >= deadline:
                    raise TaskSourceError("Source download exceeded its time bound")
                chunk = response.read1(min(16_384, MAX_DOWNLOAD_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    raise TaskSourceError("Source download exceeds 512 KiB; narrow the input")
            payload = b"".join(chunks)
            representation = "utf-8"
            if media == "text/html":
                parser = _HTMLText()
                parser.feed(payload.decode("utf-8"))
                parser.close()
                payload = "\n".join(parser.parts).encode("utf-8")
                representation = "html-text"
            # Preserve both requested and final URL attribution after redirects.
            uri = original if original == current else original + " -> " + current
            return _snapshot(uri, payload, representation)
        finally:
            connection.close()
    raise TaskSourceError("Source download did not complete")


def inspect_sources(document: dict[str, object]) -> dict[str, object]:
    if set(document) != {"repository", "commit", "paths", "local_paths", "urls"}:
        raise TaskSourceError("Source inspection request has the wrong fields")
    for key in ("paths", "local_paths", "urls"):
        items = document[key]
        if type(items) is not list or any(type(item) is not str or not item or "\0" in item for item in items):
            raise TaskSourceError("Source requests must be arrays of non-empty strings")
    if sum(len(document[key]) for key in ("paths", "local_paths", "urls")) > MAX_SOURCES:
        raise TaskSourceError("Too many source requests; narrow the task")
    sources = []
    if document["paths"]:
        if type(document["repository"]) is not str or type(document["commit"]) is not str:
            raise TaskSourceError("Git source requests need a repository and pinned commit")
        sources += [git_snapshot(Path(document["repository"]), document["commit"], path) for path in document["paths"]]
    sources += [local_snapshot(Path(path)) for path in document["local_paths"]]
    sources += [url_snapshot(url) for url in document["urls"]]
    if sum(len(source["content"].encode("utf-8")) for source in sources) > MAX_CONTEXT_BYTES:
        raise TaskSourceError("Source context exceeds 128 KiB; narrow the task")
    unique = {source["uri"]: source for source in sources}
    return {"source_schema": "agentvolve-source-snapshots-v1", "sources": [unique[uri] for uri in sorted(unique)]}


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise TaskSourceError("usage: python -m apps.coding_agent.task_sources REQUEST.json")
        with Path(sys.argv[1]).open("rb") as stream:
            payload = stream.read(65_537)
        if len(payload) > 65_536:
            raise TaskSourceError("Source inspection request exceeds its size bound")
        document = decode_json_object(payload.decode("utf-8"), TaskSourceError)
        write_document(sys.stdout, inspect_sources(document))
        return 0
    except (ValueError, OSError, http.client.HTTPException) as exc:
        print("Cannot ground task input: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
