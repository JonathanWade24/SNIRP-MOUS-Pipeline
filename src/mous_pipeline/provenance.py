"""Run provenance helpers."""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_run_manifest(subject: str, stage: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "subject": subject,
        "stage": stage,
        "python_version": sys.version,
        "platform": platform.platform(),
        "params": params,
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2))
