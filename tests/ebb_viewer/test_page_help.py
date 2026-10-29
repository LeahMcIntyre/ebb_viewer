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
