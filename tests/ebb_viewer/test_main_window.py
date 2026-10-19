"""Smoke test for ``main_window.MainWindow``.

The window wires together all 12 sidebar pages plus the badge timer and
the navigate_to signal mesh. A successful construct exercises the
sidebar layout, the stack mapping, and every page's ``__init__``.
"""

from __future__ import annotations

from pathlib import Path


def test_main_window_constructs_on_empty_project(qapp, tmp_path: Path):
    from ebb_viewer.main_window import MainWindow

    win = MainWindow(project_root=tmp_path)
    # Sidebar should contain 12 navigable rows + 4 separators = 16 items.
    assert win.pagelist.count() == 16
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
        "reclassify_page",
        "swd_review_page",
    ):
        assert hasattr(win, attr), f"MainWindow missing attribute {attr!r}"


def test_main_window_navigate_to_signal_changes_row(qapp, tmp_path: Path):
    """A page's navigate_to emission should move the sidebar selection."""
    from ebb_viewer.main_window import MainWindow

    win = MainWindow(project_root=tmp_path)
    win.home_page.navigate_to.emit("preprocess")
    # "preprocess" → row index 2 in the sidebar (after Home + separator).
    assert win.pagelist.currentRow() == 2


def test_swd_review_page_is_reachable_from_navigation(qapp, tmp_path: Path):
    from ebb_viewer.main_window import MainWindow

    win = MainWindow(project_root=tmp_path)
    win.reclassify_page.navigate_to.emit("swd_review")
    row = win.pagelist.currentRow()
    assert win.pagelist.item(row).text().startswith("4b. SWD Review")
    assert win._pages[win.stacklayout.currentIndex()] is win.swd_review_page
    win.swd_review_page.navigate_to.emit("sleep_qc")
    assert win.pagelist.item(win.pagelist.currentRow()).text().startswith("5. Sleep QC")
