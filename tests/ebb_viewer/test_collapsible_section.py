"""Tests for the reusable CollapsibleSection widget."""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel

from ebb_viewer.widgets.collapsible_section import CollapsibleSection


def test_default_starts_collapsed_and_body_hidden(qapp):
    body = QLabel("hello")
    s = CollapsibleSection("My Section", body)
    assert s.is_collapsed() is True
    assert body.isHidden() is True


def test_collapsed_false_starts_expanded(qapp):
    body = QLabel("hello")
    s = CollapsibleSection("My Section", body, collapsed=False)
    assert s.is_collapsed() is False
    assert body.isHidden() is False


def test_click_header_toggles_visibility(qapp):
    body = QLabel("hello")
    s = CollapsibleSection("My Section", body)
    # Initially collapsed; clicking expands.
    s._btn.click()
    assert s.is_collapsed() is False
    assert body.isHidden() is False
    # Clicking again collapses.
    s._btn.click()
    assert s.is_collapsed() is True
    assert body.isHidden() is True


def test_set_collapsed_programmatic(qapp):
    body = QLabel("hello")
    s = CollapsibleSection("My Section", body, collapsed=False)
    s.set_collapsed(True)
    assert s.is_collapsed() is True
    assert body.isHidden() is True
    s.set_collapsed(False)
    assert s.is_collapsed() is False
    assert body.isHidden() is False


def test_toggled_visibility_signal_fires_on_click(qapp):
    body = QLabel("hello")
    s = CollapsibleSection("My Section", body)
    events: list[bool] = []
    s.toggled_visibility.connect(events.append)
    s._btn.click()
    assert events == [True]
    s._btn.click()
    assert events == [True, False]


def test_toggled_visibility_signal_fires_on_set_collapsed(qapp):
    body = QLabel("hello")
    s = CollapsibleSection("My Section", body, collapsed=False)
    events: list[bool] = []
    s.toggled_visibility.connect(events.append)
    s.set_collapsed(True)
    assert events == [False]
    s.set_collapsed(False)
    assert events == [False, True]


def test_header_displays_title(qapp):
    s = CollapsibleSection("Compute Hours", QLabel("body"))
    assert s._btn.text() == "Compute Hours"
