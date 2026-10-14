"""Shared visual constants for ebb_viewer pages."""

# Background colors for sleep_qc / psd_status values (hex, for QColor or CSS).
STATUS_COLOR_HEX: dict[str, str] = {
    "ok": "#d4edda",  # green
    "needs_review": "#FFF3CD",  # yellow
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


# ---------------------------------------------------------------------------
# Zone header — bigger sibling of a section label, used to break a vertical
# page into named functional zones (e.g. "1. SETUP" / "2. WHAT TO COMPUTE")
# without nesting more group boxes. Returns a QLabel so the caller can add
# it to whatever layout it owns.
# ---------------------------------------------------------------------------


def zone_header_qss() -> str:
    return (
        "color: #1a5fa8; font-size: 11px; font-weight: bold; "
        "letter-spacing: 1px; padding: 8px 0 2px 0; "
        "border-bottom: 1px solid #d0d0d0;"
    )