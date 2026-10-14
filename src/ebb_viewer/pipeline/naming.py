# Re-exports `parse_animal_id` from the canonical `ebb.core.naming` module
# so existing GUI-side imports (`from ebb_viewer.pipeline.naming import
# parse_animal_id`) keep working.
from ebb.core.naming import parse_animal_id

__all__ = ["parse_animal_id", "drink_mask_rel"]


def drink_mask_rel(animal_id: str) -> str:
    """Relative path to the drink mask .npy for an animal (relative to project_root)."""
    return f"drink_masks/{animal_id}.npy"
