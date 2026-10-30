"""Tests for ``widgets/page_help.py``: every help entry is reachable from its page."""

from __future__ import annotations

import pytest

from ebb_viewer.widgets.page_help import PAGE_HELP, HelpButton, title_row


def test_unknown_page_key_raises(qapp):
    with pytest.raises(KeyError):
        HelpButton("nope")


def test_title_row_has_a_help_button_for_its_page(qapp):
    row = title_row("Title", "reclassify")
    btn = row.findChild(HelpButton)
    assert btn is not None and btn.page_key == "reclassify"


@pytest.mark.parametrize("key", sorted(PAGE_HELP))
def test_help_entries_have_text(key):
    title, html = PAGE_HELP[key]
    assert title and "<h4>" in html


def test_pages_carry_a_help_button(qapp, tmp_path):
    from ebb_viewer.pages.reclassify import ReclassifyPage
    from ebb_viewer.pages.swd_review import SwdReviewPage

    for cls, key in ((ReclassifyPage, "reclassify"), (SwdReviewPage, "swd_review")):
        page = cls(project_root=tmp_path)
        assert [b.page_key for b in page.findChildren(HelpButton)] == [key]


def test_every_help_entry_is_used_by_a_page():
    from pathlib import Path

    import ebb_viewer

    sources = "\n".join(p.read_text() for p in Path(ebb_viewer.__file__).parent.rglob("*.py"))
    for key in PAGE_HELP:
        shown = (
            f', "{key}")' in sources
            or f'HelpButton("{key}")' in sources
            or f'PAGE_HELP["{key}"]' in sources
        )
        assert shown, f"help entry {key!r} is not shown by any page"


def test_simple_pages_carry_their_help_button(qapp, tmp_path):
    from ebb_viewer.pages.preprocess import PreprocessPage
    from ebb_viewer.pages.spindle import SpindleWritePage

    for cls, key in ((PreprocessPage, "preprocess"), (SpindleWritePage, "spindle")):
        page = cls(project_root=tmp_path)
        assert [b.page_key for b in page.findChildren(HelpButton)] == [key]
