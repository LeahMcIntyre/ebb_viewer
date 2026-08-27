"""Shared pytest fixtures for the whole test tree."""

import os
import sys

import pytest


@pytest.fixture(scope="session")
def qapp():
    """A session-scoped QApplication so widget tests can construct Qt objects.

    Falls back to the offscreen platform plugin when no display is available
    (CI, headless dev boxes) so tests don't crash trying to open a window.
    """
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)
