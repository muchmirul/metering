"""Externally sampled process and cgroup resource observations."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class ResourceObservation:
    cpu_microseconds: int | None
    memory_peak_bytes: int | None
    processes_peak: int | None
    storage_write_bytes: int | None
    wall_milliseconds: int
    source: str

    def document(self) -> dict[str, object]:
        return {
            "cpu_microseconds": self.cpu_microseconds,
            "memory_peak_bytes": self.memory_peak_bytes,
            "processes_peak": self.processes_peak,
            "source": self.source,
            "storage_write_bytes": self.storage_write_bytes,
            "wall_milliseconds": self.wall_milliseconds,
        }


class ResourceObserver:
    """Poll metrics outside a candidate process until stopped."""

    def __init__(self, target: Callable[[], tuple[str, Path] | None]) -> None:
        self._target = target
        self._start = time.monotonic_ns()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._cpu: int | None = None
        self._memory: int | None = None
        self._processes: int | None = None
        self._storage: int | None = None
        self._source = "unavailable"
        self._thread = threading.Thread(
            target=self._poll, name="harness-resource-observer", daemon=True
        )
        self.sample()
        self._thread.start()

    def _poll(self) -> None:
        while not self._stop.wait(0.01):
            self.sample()
        self.sample()

    def sample(self) -> None:
        target = self._target()
        if target is None:
            return
        kind, path = target
        try:
            if kind == "cgroup-v2":
                metrics = _cgroup_metrics(path)
            else:
                metrics = _process_tree_metrics(int(path.name))
        except (OSError, ValueError):
            return
        with self._lock:
            self._source = kind
            cpu, memory, processes, storage = metrics
            self._cpu = _maximum(self._cpu, cpu)
            self._memory = _maximum(self._memory, memory)
            self._processes = _maximum(self._processes, processes)
            self._storage = _maximum(self._storage, storage)

    def stop(self) -> ResourceObservation:
        self._stop.set()
        self._thread.join(timeout=2)
        wall = max(0, (time.monotonic_ns() - self._start) // 1_000_000)
        with self._lock:
            return ResourceObservation(
                cpu_microseconds=self._cpu,
                memory_peak_bytes=self._memory,
                processes_peak=self._processes,
                storage_write_bytes=self._storage,
                wall_milliseconds=wall,
                source=self._source,
            )


def _maximum(old: int | None, new: int | None) -> int | None:
    if new is None:
        return old
    return new if old is None else max(old, new)


def cgroup_for_pid(pid: int) -> Path | None:
    """Resolve a Linux unified cgroup path for one externally observed PID."""

    try:
        source = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in source.splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[0] == "0" and fields[1] == "":
            relative = fields[2].lstrip("/")
            root = Path("/sys/fs/cgroup")
            candidate = root / relative
            return candidate if candidate.is_dir() else None
    return None


def _read_integer(path: Path) -> int | None:
    try:
        source = path.read_text(encoding="ascii").strip()
        return int(source)
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _cpu_usage(path: Path) -> int | None:
    try:
        lines = (path / "cpu.stat").read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    for line in lines:
        fields = line.split()
        if len(fields) == 2 and fields[0] == "usage_usec":
            try:
                return int(fields[1])
            except ValueError:
                return None
    return None


def _io_writes(path: Path) -> int | None:
    try:
        lines = (path / "io.stat").read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    total = 0
    found = False
    for line in lines:
        for field in line.split()[1:]:
            if field.startswith("wbytes="):
                try:
                    total += int(field.split("=", 1)[1])
                except ValueError:
                    return None
                found = True
    return total if found else None


def _cgroup_metrics(
    path: Path,
) -> tuple[int | None, int | None, int | None, int | None]:
    memory = _read_integer(path / "memory.peak")
    if memory is None:
        memory = _read_integer(path / "memory.current")
    processes = _read_integer(path / "pids.peak")
    if processes is None:
        processes = _read_integer(path / "pids.current")
    return _cpu_usage(path), memory, processes, _io_writes(path)


def _process_ids() -> list[int]:
    result: list[int] = []
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return result
    for entry in entries:
        if entry.name.isdigit():
            result.append(int(entry.name))
    return result


def _stat_fields(pid: int) -> tuple[int, int, int] | None:
    try:
        source = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return None
    close = source.rfind(")")
    if close < 0:
        return None
    fields = source[close + 2 :].split()
    try:
        ppid = int(fields[1])
        user_ticks = int(fields[11])
        system_ticks = int(fields[12])
    except (IndexError, ValueError):
        return None
    return ppid, user_ticks, system_ticks


def _descendants(root: int) -> list[int]:
    children: dict[int, list[int]] = {}
    for pid in _process_ids():
        fields = _stat_fields(pid)
        if fields is not None:
            children.setdefault(fields[0], []).append(pid)
    result: list[int] = []
    pending = [root]
    while pending:
        pid = pending.pop()
        if pid in result:
            continue
        result.append(pid)
        pending.extend(children.get(pid, []))
    return result


def _status_memory(pid: int) -> int | None:
    try:
        lines = Path(f"/proc/{pid}/status").read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    values: dict[str, int] = {}
    for line in lines:
        fields = line.split()
        if len(fields) >= 2 and fields[0] in {"VmHWM:", "VmRSS:"}:
            try:
                values[fields[0]] = int(fields[1]) * 1024
            except ValueError:
                pass
    return values.get("VmHWM:", values.get("VmRSS:"))


def _process_write_bytes(pid: int) -> int | None:
    try:
        lines = Path(f"/proc/{pid}/io").read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError, PermissionError):
        return None
    for line in lines:
        fields = line.split()
        if len(fields) == 2 and fields[0] == "write_bytes:":
            try:
                return int(fields[1])
            except ValueError:
                return None
    return None


def _process_tree_metrics(
    root: int,
) -> tuple[int | None, int | None, int | None, int | None]:
    pids = _descendants(root)
    ticks = 0
    memory = 0
    writes = 0
    found_ticks = found_memory = found_writes = False
    for pid in pids:
        fields = _stat_fields(pid)
        if fields is not None:
            ticks += fields[1] + fields[2]
            found_ticks = True
        value = _status_memory(pid)
        if value is not None:
            memory += value
            found_memory = True
        value = _process_write_bytes(pid)
        if value is not None:
            writes += value
            found_writes = True
    try:
        ticks_per_second = os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError):
        ticks_per_second = 100
    cpu = ticks * 1_000_000 // ticks_per_second if found_ticks else None
    return (
        cpu,
        memory if found_memory else None,
        len(pids),
        writes if found_writes else None,
    )
