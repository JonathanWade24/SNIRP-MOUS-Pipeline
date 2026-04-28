"""Normalise CTF-style channel type values in BIDS channels.tsv files.

Run against a BIDS root to fix lowercase/non-standard channel types produced
by older MNE-BIDS or CTF export tools so that fMRIPrep's bids-validator accepts them.

Usage:
    python scripts/normalize_channels_tsv.py <bids_root>
"""

from __future__ import annotations

import sys
from pathlib import Path

from mous_pipeline.m0_intake.bids_convert import normalize_channel_type


def normalise_file(path: Path) -> tuple[bool, list[str]]:
    """Return (changed, non_canonical_types). Writes in-place if changed."""
    lines = path.read_text().splitlines(keepends=True)
    if not lines:
        return False, []

    header = lines[0].rstrip("\n").split("\t")
    if "type" not in header:
        return False, []
    type_col = header.index("type")

    changed = False
    non_canonical: list[str] = []
    out_lines = [lines[0]]

    for line in lines[1:]:
        parts = line.rstrip("\n").split("\t")
        if len(parts) > type_col:
            original = parts[type_col]
            mapped = normalize_channel_type(original)
            if mapped != original:
                parts[type_col] = mapped
                changed = True
                non_canonical.append(original)
        out_lines.append("\t".join(parts) + "\n")

    if changed:
        path.write_text("".join(out_lines))

    return changed, sorted(set(non_canonical))


def main(bids_root: Path) -> None:
    tsv_files = sorted(bids_root.glob("sub-*/meg/*_channels.tsv"))
    if not tsv_files:
        print(f"No channels.tsv files found under {bids_root}")
        return

    n_changed = 0
    n_ok = 0
    all_non_canonical: dict[str, list[str]] = {}

    for tsv in tsv_files:
        changed, non_canonical = normalise_file(tsv)
        rel = tsv.relative_to(bids_root)
        if changed:
            print(f"  fixed  {rel}")
            n_changed += 1
        else:
            print(f"  ok     {rel}")
            n_ok += 1
        if non_canonical:
            all_non_canonical[str(rel)] = non_canonical

    print(f"\nSummary: {n_changed} fixed, {n_ok} already compliant")
    if all_non_canonical:
        print("\nNon-canonical original types mapped to BIDS-safe labels:")
        for f, types in all_non_canonical.items():
            print(f"  {f}: {types}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <bids_root>")
        sys.exit(1)
    main(Path(sys.argv[1]).expanduser().resolve())
