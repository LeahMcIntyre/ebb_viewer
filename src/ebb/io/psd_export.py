"""Export a finalized PSD pkl to an Excel workbook for GraphPad Prism.

One sheet per channel × state combo. Each sheet has frequency in column A
and one column per animal — the layout Prism expects (X = frequency down,
Y-replicates = animals across).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pickle

import numpy as np
import pandas as pd

from ebb.core.naming import parse_animal_id
from ebb.io.psd_store import PSDStore

DEFAULT_CHANNEL_NAMES: tuple[str, ...] = ("LFC", "RSC", "LSC")

# Excel caps sheet names at 31 chars.
_SHEET_NAME_MAX = 31


def _sheet_name(channel: str, state: str) -> str:
    name = f"{channel}_{state}"
    return name[:_SHEET_NAME_MAX]


def _excluded_in_pkl(pkl_path: Path) -> dict[str, str]:
    """``{animal: reason}`` from the ``excluded`` fields Finalize writes into psds_final.pkl."""
    with open(pkl_path, "rb") as f:
        items = pickle.load(f)
    if isinstance(items, dict):
        items = [items]
    return {
        parse_animal_id(rec["path"]): rec.get("exclusion_reason", "")
        for rec in items
        if rec.get("excluded")
    }


def export_psds_to_xlsx(
    pkl_path: str | Path,
    out_path: str | Path,
    *,
    channel_names: Sequence[str] = DEFAULT_CHANNEL_NAMES,
) -> Path:
    """Read ``psds_final.pkl`` and write one ``.xlsx`` per channel × state combo.

    Each sheet's column A is ``frequency_hz``; remaining columns are PSD
    power for each animal, sorted alphabetically. Missing (animal, channel,
    state) cells are written as blanks.
    """
    pkl_path = Path(pkl_path)
    out_path = Path(out_path)

    store = PSDStore(
        pkl_path,
        channel_names=channel_names,
        parse_animal=lambda rec: parse_animal_id(rec["path"]),
    )

    freqs = np.asarray(store.freqs(), float)
    animals = store.animals()

    # Collect every (channel, state) pair that appears in the pkl.
    combos: set[tuple[str, str]] = set()
    for animal in animals:
        for state, ch_map in store.by_animal[animal].items():
            for channel in ch_map:
                combos.add((channel, state))

    if not combos:
        raise ValueError(f"No PSD records found in {pkl_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for channel, state in sorted(combos):
            df = pd.DataFrame({"frequency_hz": freqs})
            for animal in animals:
                ch_map = store.by_animal[animal].get(state, {})
                pair = ch_map.get(channel)
                if pair is None:
                    df[animal] = np.nan
                else:
                    df[animal] = np.asarray(pair[1], float)
            df.to_excel(writer, sheet_name=_sheet_name(channel, state), index=False)
        # Prism reads the per-combo sheets; this extra sheet (only when the sealed pkl marks
        # exclusions) says which animal columns were excluded in Sleep QC.
        excluded = _excluded_in_pkl(pkl_path)
        if excluded:
            pd.DataFrame(
                {"animal": sorted(excluded), "reason": [excluded[a] for a in sorted(excluded)]}
            ).to_excel(writer, sheet_name="excluded_animals", index=False)

    return out_path
