"""Qt platform shims applied before any ``QApplication`` is constructed."""

import os
import sys


def force_xcb_on_wayland() -> None:
    """Force the xcb (X11) backend on Linux/Wayland sessions.

    PyQt6's Wayland backend miscomputes QMessageBox size hints, clipping the
    title bar and body text on short dialogs. Must be called before the
    ``QApplication`` is constructed.
    """
    if sys.platform == "linux" and os.environ.get("XDG_SESSION_TYPE") == "wayland":
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
