"""Shared pytest fixtures for the whole test tree."""

import gc
import os
import sys

import pytest

# The Qt tests run headless (offscreen), where there is no OpenGL: keep the viewer on software rendering.
os.environ["EBB_VIEWER_USE_OPENGL"] = "0"

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


@pytest.fixture(autouse=True)
def _flush_qt_between_tests():
    """Collect garbage and process Qt events after every test.

    Without this, a pyqtgraph scene could be left with a queued update for an item whose widget
    had already been deleted; whichever later test next called processEvents() then crashed in
    QGraphicsScene::itemsBoundingRect, and which test that was depended on when Python's garbage
    collector happened to run. Cleaning up here makes the timing deterministic.
    """
    yield
    if "PyQt6.QtWidgets" not in sys.modules:
        return
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        gc.collect()  # drop unreferenced widgets now, not at some later GC pass
        app.processEvents()
