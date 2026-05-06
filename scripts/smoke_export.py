"""Smoke-test the mask-export pipeline against a real project.

Usage::

    python scripts/smoke_export.py /path/to/project [--run-name default] [--animal Mice-1234] [--combo LFC_RSC]

Picks one (animal, combo) pair, runs the full export, and prints a summary
plus the first few rows of each output CSV. Useful for sanity-checking
Phase 1 + Phase 2 before wiring up the UI.

Output goes to ``<project_root>/exports/smoke_test/`` by default.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ebb_viewer.pipeline import psd_params
from ebb_viewer.pipeline.manifest import Manifest
from ebb_viewer.pipeline.mask_export import default_pairs, export_animal


def _read_csv_head(path: Path, n: int = 6) -> str:
    """Return the first ``n`` lines of a CSV, indented for printing."""
    if not path.exists():
        return "  (file not written)"
    lines = path.read_text().splitlines()[:n]
    return "\n".join(f"    {line}" for line in lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project_root", type=Path, help="Path to ebb project root")
    p.add_argument(
        "--run-name",
        default="default",
        help="PSD run whose psd_params.json to load (default: 'default')",
    )
    p.add_argument(
        "--animal",
        default=None,
        help="Animal ID to export (default: first OK run in manifest)",
    )
    p.add_argument(
        "--combo",
        default=None,
        help="Channel combo (default: first OK combo for the chosen animal)",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output dir (default: <project_root>/exports/smoke_test)",
    )
    args = p.parse_args()

    if not args.project_root.is_dir():
        print(f"ERROR: project_root not found: {args.project_root}")
        return 1

    out_dir = args.out_dir or (args.project_root / "exports" / "smoke_test")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Project root: {args.project_root}")
    print(f"Output dir:   {out_dir}")

    # --- params ---
    params = psd_params.load(args.project_root, args.run_name)
    if params is None:
        print(f"ERROR: no psd_params.json found at psd/{args.run_name}/")
        print(f"       available runs: {psd_params.list_runs(args.project_root)}")
        return 1
    print(f"Loaded PSD run params: '{args.run_name}'")
    print(
        f"  states={params.get('states')}  hour_windows={params.get('hour_windows')}  s_prob={params.get('s_prob')}"
    )

    # --- pick (animal, combo) ---
    manifest = Manifest.load(args.project_root)
    pairs = default_pairs(manifest)
    if not pairs:
        print("ERROR: no OK runs in the manifest")
        return 1

    if args.animal is not None:
        if args.combo is not None:
            chosen = (args.animal, args.combo)
        else:
            matches = [p for p in pairs if p[0] == args.animal]
            if not matches:
                print(f"ERROR: no OK run for animal {args.animal!r}")
                print(f"       OK animals: {sorted({a for a, _ in pairs})}")
                return 1
            chosen = matches[0]
    else:
        chosen = pairs[0]
    animal, combo = chosen
    print(f"Exporting: {animal} / {combo}")

    # --- run ---
    result = export_animal(
        project_root=args.project_root,
        out_dir=out_dir,
        manifest=manifest,
        animal_id=animal,
        combo=combo,
        params=params,
    )

    print()
    if result.status == "error":
        print(f"FAILED: {result.message}")
        return 2

    print("SUCCESS. Files written:")
    for kind, path in result.paths.items():
        print(f"  {kind:18s} {path}")

    print("\n--- states.csv (head) ---")
    print(_read_csv_head(result.paths["states"]))
    print("\n--- artifacts.csv (head) ---")
    print(_read_csv_head(result.paths["artifacts"]))
    print("\n--- clean_per_state.csv (head) ---")
    print(_read_csv_head(result.paths["clean_per_state"]))
    print("\n--- meta.json ---")
    print(_read_csv_head(result.paths["meta"], n=200))
    return 0


if __name__ == "__main__":
    sys.exit(main())
