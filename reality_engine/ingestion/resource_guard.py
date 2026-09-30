"""Adaptive system-load guard for bounded local document ingestion.

The guard deliberately targets 90% rather than the 97% user ceiling. That leaves
headroom for Windows, the desktop compositor, and unrelated processes. It is a
between-stage governor, not a false claim of instantaneous OS-level capping: OCR
and filesystem syscalls remain indivisible operations. The ingestion pipeline
therefore combines this guard with one ingest worker, bounded vector batches, and
a GPU duty target below the ceiling.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - production manifest includes psutil
    psutil = None  # type: ignore[assignment]

logger = logging.getLogger("reality_engine.resource_guard")


@dataclass(frozen=True)
class ResourceSnapshot:
    cpu_percent: Optional[float]
    disk_percent: Optional[float]
    memory_percent: Optional[float]
    free_bytes: Optional[int]


class ResourceGuard:
    """Pause before expensive phases while system load is above the target."""
    def __init__(
        self,
        *,
        cpu_target: float = 0.90,
        disk_target: float = 0.90,
        memory_target: float = 0.85,
        poll_seconds: float = 0.25,
        sample_seconds: float = 0.05,
        max_wait_seconds: float = 30.0,
        min_free_gb: float = 20.0,
        root: str | Path | None = None,
    ) -> None:
        self.cpu_target = min(0.96, max(0.50, float(cpu_target)))
        self.disk_target = min(0.96, max(0.50, float(disk_target)))
        self.memory_target = min(0.96, max(0.50, float(memory_target)))
        self.poll_seconds = max(0.05, float(poll_seconds))
        self.sample_seconds = max(0.02, float(sample_seconds))
        self.max_wait_seconds = max(0.0, float(max_wait_seconds))
        self.min_free_bytes = max(0.0, float(min_free_gb)) * 1024**3
        self.root = Path(root) if root else Path.cwd()
        self._last_disk = None
        self._last_disk_at = time.perf_counter()
        self._process = psutil.Process() if psutil is not None else None
        self._set_process_priority()

    @classmethod
    def from_env(cls, root: str | Path | None = None) -> "ResourceGuard":
        def number(name: str, default: float) -> float:
            try:
                return float(os.environ.get(name, default))
            except (TypeError, ValueError):
                return default

        return cls(
            cpu_target=number("REALITY_ENGINE_CPU_TARGET", 0.90),
            disk_target=number("REALITY_ENGINE_DISK_TARGET", 0.90),
            memory_target=number("REALITY_ENGINE_MEMORY_TARGET", 0.85),
            poll_seconds=number("REALITY_ENGINE_RESOURCE_POLL", 0.25),
            sample_seconds=number("REALITY_ENGINE_RESOURCE_SAMPLE", 0.05),
            max_wait_seconds=number("REALITY_ENGINE_RESOURCE_MAX_WAIT", 30.0),
            min_free_gb=number("REALITY_ENGINE_MIN_FREE_GB", 20.0),
            root=root,
        )

    def _set_process_priority(self) -> None:
        if self._process is None:
            return
        try:
            if os.name == "nt":
                self._process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            else:  # pragma: no cover - local production target is Windows
                self._process.nice(10)
        except (AttributeError, OSError, psutil.Error):  # type: ignore[union-attr]
            logger.debug("resource guard could not lower process priority", exc_info=True)

    def _disk_percent(self) -> Optional[float]:
        if psutil is None:
            return None
        try:
            now = time.perf_counter()
            current = psutil.disk_io_counters(perdisk=True)
            elapsed_ms = max(1.0, (now - self._last_disk_at) * 1000.0)
            self._last_disk_at = now
            previous = self._last_disk
            self._last_disk = current
            if previous is None or not current:
                return None
            values = []
            for name, counter in current.items():
                old = previous.get(name)
                if old is None:
                    continue
                busy_ms = max(0, int(getattr(counter, "read_time", 0)) - int(getattr(old, "read_time", 0)))
                busy_ms += max(0, int(getattr(counter, "write_time", 0)) - int(getattr(old, "write_time", 0)))
                values.append(min(100.0, 100.0 * busy_ms / elapsed_ms))
            return max(values) if values else None
        except Exception:  # pragma: no cover - platform counter differences
            return None

    def snapshot(self) -> ResourceSnapshot:
        if psutil is None:
            return ResourceSnapshot(None, None, None, None)
        try:
            cpu = float(psutil.cpu_percent(interval=self.sample_seconds))
        except Exception:
            cpu = None
        disk = self._disk_percent()
        try:
            memory = float(psutil.virtual_memory().percent)
        except Exception:
            memory = None
        try:
            free = int(psutil.disk_usage(str(self.root)).free)
        except Exception:
            free = None
        return ResourceSnapshot(cpu, disk, memory, free)

    def wait_for_headroom(self, phase: str) -> ResourceSnapshot:
        """Wait briefly for headroom, then proceed with a soft-cap warning."""
        started = time.perf_counter()
        warned = False
        max_checks = max(1, int(self.max_wait_seconds / self.poll_seconds) + 1)
        for check in range(max_checks):
            snap = self.snapshot()
            overloaded = (
                snap.cpu_percent is not None and snap.cpu_percent / 100.0 > self.cpu_target
            ) or (
                snap.disk_percent is not None and snap.disk_percent / 100.0 > self.disk_target
            ) or (
                snap.memory_percent is not None and snap.memory_percent / 100.0 > self.memory_target
            )
            low_disk = snap.free_bytes is not None and snap.free_bytes < self.min_free_bytes
            if low_disk:
                raise RuntimeError(
                    f"resource guard: free disk below {self.min_free_bytes / 1024**3:.1f} GiB"
                )
            if not overloaded:
                return snap
            elapsed = time.perf_counter() - started
            if check + 1 >= max_checks or elapsed >= self.max_wait_seconds:
                logger.warning(
                    "resource guard proceeding after %.1fs phase=%s cpu=%s%% disk=%s%% memory=%s%%; caps are soft",
                    elapsed,
                    phase,
                    "?" if snap.cpu_percent is None else f"{snap.cpu_percent:.1f}",
                    "?" if snap.disk_percent is None else f"{snap.disk_percent:.1f}",
                    "?" if snap.memory_percent is None else f"{snap.memory_percent:.1f}",
                )
                return snap
            if not warned:
                logger.info(
                    "resource guard waiting phase=%s cpu=%s%% disk=%s%% memory=%s%% targets=%.0f%%/%.0f%%/%.0f%%",
                    phase,
                    "?" if snap.cpu_percent is None else f"{snap.cpu_percent:.1f}",
                    "?" if snap.disk_percent is None else f"{snap.disk_percent:.1f}",
                    "?" if snap.memory_percent is None else f"{snap.memory_percent:.1f}",
                    self.cpu_target * 100,
                    self.disk_target * 100,
                    self.memory_target * 100,
                )
                warned = True
            time.sleep(self.poll_seconds)
