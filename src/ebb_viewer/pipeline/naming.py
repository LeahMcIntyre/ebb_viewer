from pathlib import Path
from typing import Union

# All valid channel combos used by the pipeline
CHANNEL_COMBOS = ["LFC_RSC", "LFC_LSC", "RSC_LSC", "LFC", "RSC", "LSC"]


def parse_animal_id(path: Union[str, Path]) -> str:
    """Extract animal ID (everything before first '_') from a file or path stem."""
    stem = Path(path).stem
    return stem.split("_")[0] if "_" in stem else stem


def drink_mask_rel(animal_id: str) -> str:
    """Relative path to the drink mask .npy for an animal (relative to project_root)."""
    return f"drink_masks/{animal_id}.npy"
