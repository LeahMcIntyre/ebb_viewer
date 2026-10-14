"""Smoke test for ``main_window.MainWindow``.

The window wires together all 10 sidebar pages plus the badge timer and
the navigate_to signal mesh. A successful construct exercises the
sidebar layout, the stack mapping, and every page's ``__init__``.
"""

from __future__ import annotations

from pathlib import Path


def test_main_window_constructs_on_empty_project(qapp, tmp_path: Path):
    from ebb_viewer.main_window import MainWindow

    win = MainWindow(project_root=tmp_path)
    # Sidebar should contain 10 navigable rows + 4 separators = 14 items.
    assert win.pagelist.count() == 14
    # Initially showing the home page (stack index 0).
    assert win.stacklayout.currentIndex() == 0
    # All page attributes were created.
    for attr in (
        "home_page",
        "preprocess_page",
        "spindle_write_page",
        "spindle_upload_page",
        "sleep_qc_page",
        "psd_page",
        "psd_visualizer_page",
        "drink_mask_page",
        "finalize_page",
        "export_masks_page",
    ):
        assert hasattr(win, attr), f"MainWindow missing attribute {attr!r}"


def test_main_window_navigate_to_signal_changes_row(qapp, tmp_path: Path):
    """A page's navigate_to emission should move the sidebar selection."""
    from ebb_viewer.main_window import MainWindow

    win = MainWindow(project_root=tmp_path)
    win.home_page.navigate_to.emit("preprocess")
    # "preprocess" → row index 2 in the sidebar (after Home + separator).
    assert win.pagelist.currentRow() == 2
