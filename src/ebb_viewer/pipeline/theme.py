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


# ---------------------------------------------------------------------------
# Primary-action button — applied to "Run X" / "Apply X" / "Export" /
# "Finalize" / "Upload & Download" buttons on pipeline pages so the primary
# affordance reads consistently across the app.
# ---------------------------------------------------------------------------

PRIMARY_BUTTON_QSS = (
    "QPushButton { background: #1a5fa8; color: white; font-weight: bold; "
    "padding: 8px 16px; border-radius: 4px; font-size: 13px; }"
    "QPushButton:hover:!disabled { background: #154d8a; }"
    "QPushButton:disabled { background: #c0c0c0; color: #f0f0f0; }"
)


def apply_primary_button(btn) -> None:
    """Style ``btn`` as the primary action on a page.

    Replaces any existing stylesheet on ``btn`` — call last when constructing.
    """
    btn.setStyleSheet(PRIMARY_BUTTON_QSS)
    btn.setMinimumHeight(36)


# ---------------------------------------------------------------------------
# Secondary-action button — outlined complement to ``apply_primary_button``.
# Use only when a secondary button sits directly next to a primary one and
# the size/style mismatch would read as jarring. Native Qt styling is fine
# everywhere else.
# ---------------------------------------------------------------------------

SECONDARY_BUTTON_QSS = (
    "QPushButton { background: white; color: #1a5fa8; "
    "border: 1px solid #1a5fa8; padding: 6px 14px; "
    "border-radius: 4px; font-weight: 500; }"
    "QPushButton:hover:!disabled { background: #eef4fc; }"
    "QPushButton:disabled { color: #999; border-color: #ccc; background: #f5f5f5; }"
)


def apply_secondary_button(btn) -> None:
    """Style ``btn`` as a secondary action paired with a primary action."""
    btn.setStyleSheet(SECONDARY_BUTTON_QSS)
    btn.setMinimumHeight(36)


