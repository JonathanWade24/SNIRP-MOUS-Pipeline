"""Optional RSS sampling for parallelization / RAM budgeting (stage boundaries + peak)."""

from __future__ import annotations

import platform
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def current_rss_bytes() -> int | None:
    """Best-effort resident set size for this process (current on Linux; else high-water via getrusage)."""
    system = platform.system()
    try:
        if system == "Linux":
            status = Path("/proc/self/status")
            if not status.is_file():
                return None
            for line in status.read_text().splitlines():
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    return int(parts[1]) * 1024  # value is kB
            return None
        import resource

        ru = resource.getrusage(resource.RUSAGE_SELF)
        rss = int(ru.ru_maxrss)
        # ru_maxrss: bytes on macOS; kilobytes on most other Unix (see resource docs).
        if system == "Darwin":
            return rss
        return rss * 1024
    except OSError:
        return None


def rss_bytes_to_mb(n: int | None) -> float | None:
    if n is None:
        return None
    return round(n / (1024 * 1024), 3)


@dataclass
class StageRSSProbe:
    """Track RSS at stage start/done and optionally poll for peak between events."""

    live_log_path: Path | None = None
    sample_interval_s: float = 0.5
    _peak_bytes: int = 0
    _per_stage: dict[str, dict[str, int | None]] = field(default_factory=dict)
    _sampler: threading.Thread | None = None
    _stop_sampler: threading.Event = field(default_factory=threading.Event)

    def start_background_sampler(self) -> None:
        if self.sample_interval_s <= 0:
            return
        if self._sampler is not None:
            return

        def _loop() -> None:
            while not self._stop_sampler.wait(self.sample_interval_s):
                b = current_rss_bytes()
                if b is not None and b > self._peak_bytes:
                    self._peak_bytes = b

        self._stop_sampler.clear()
        self._sampler = threading.Thread(target=_loop, name="rss-sampler", daemon=True)
        self._sampler.start()

    def stop_background_sampler(self) -> None:
        self._stop_sampler.set()
        if self._sampler is not None:
            self._sampler.join(timeout=self.sample_interval_s * 2 + 1.0)
            self._sampler = None

    def _bump_peak(self) -> None:
        b = current_rss_bytes()
        if b is not None and b > self._peak_bytes:
            self._peak_bytes = b

    def record(self, event: str, stage: str) -> None:
        self._bump_peak()
        key = stage
        if key not in self._per_stage:
            self._per_stage[key] = {"rss_start_bytes": None, "rss_done_bytes": None}
        row = self._per_stage[key]
        if event == "start":
            row["rss_start_bytes"] = current_rss_bytes()
        elif event == "done":
            row["rss_done_bytes"] = current_rss_bytes()
        if self.live_log_path is not None:
            rss = current_rss_bytes()
            mb = rss_bytes_to_mb(rss)
            peak_mb = rss_bytes_to_mb(self._peak_bytes)
            msg = f"[rss] event={event} stage={stage} rss_mb={mb} peak_mb_so_far={peak_mb}"
            self.live_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.live_log_path.open("a") as f:
                f.write(msg + "\n")

    def summary(self) -> dict[str, Any]:
        self._bump_peak()
        table: dict[str, dict[str, float | None]] = {}
        for st, row in self._per_stage.items():
            start_b = row.get("rss_start_bytes")
            done_b = row.get("rss_done_bytes")
            start_mb = rss_bytes_to_mb(start_b if isinstance(start_b, int) else None)
            done_mb = rss_bytes_to_mb(done_b if isinstance(done_b, int) else None)
            delta = None
            if isinstance(start_b, int) and isinstance(done_b, int):
                delta = round((done_b - start_b) / (1024 * 1024), 3)
            table[st] = {"rss_start_mb": start_mb, "rss_done_mb": done_mb, "delta_mb": delta}
        return {
            "peak_rss_bytes": self._peak_bytes,
            "peak_rss_mb": rss_bytes_to_mb(self._peak_bytes),
            "per_stage_mb": table,
            "platform": platform.platform(),
        }
