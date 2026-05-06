"""Shared visual constants for ebb_viewer pages."""

# Badge/cell background colors for channel combos (hex, for QColor or CSS).
# Used in table cells and sidebar badges.
COMBO_BADGE_HEX: dict[str, str] = {
    "LFC_RSC": "#5ba3d9",
    "LFC_LSC": "#ffab5e",
    "RSC_LSC": "#5ec45e",
    "LFC": "#e86e6e",
    "RSC": "#b89cd8",
    "LSC": "#b3896e",
}

# Line/plot colors for channel combos (RGB 0–255 tuples, for matplotlib).
COMBO_PLOT_RGB: dict[str, tuple[int, int, int]] = {
    "LFC_RSC": (31, 119, 180),
    "LFC_LSC": (255, 127, 14),
    "RSC_LSC": (44, 160, 44),
    "LFC": (214, 39, 40),
    "RSC": (148, 103, 189),
    "LSC": (140, 86, 75),
}

# Background colors for sleep_qc / psd_status values (hex, for QColor or CSS).
STATUS_COLOR_HEX: dict[str, str] = {
    "ok": "#d4edda",  # green
    "needs_review": "#FFF3CD",  # yellow
    "needs_rerun": "#E97B7B",  # red
    "rejected": "#e0e0e0",  # gray
    "needs_drink_mask": "#E97B7B",  # red
    "drink_mask_applied": "#d4edda",  # green
}
