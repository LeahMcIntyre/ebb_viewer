"""Helpers for running work off the GUI thread."""

import threading

from PyQt6.QtCore import QEventLoop, QObject, QThread, QTimer


def run_keeping_gui_alive(fn, *args, **kwargs):
    """Call ``fn`` on a plain thread and return its result (or re-raise its error).

    The caller still waits, but the Qt event loop keeps running (user input is
    ignored), so the window manager doesn't flag the app as "not responding".
    ``fn`` must not touch widgets.
    """
    outcome: dict = {}

    def target():
        try:
            outcome["value"] = fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001 — re-raised on the GUI thread below
            outcome["error"] = e

    thread = threading.Thread(target=target, daemon=True)
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(50)
    poll.timeout.connect(lambda: None if thread.is_alive() else loop.quit())
    thread.start()
    poll.start()
    loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    poll.stop()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def launch_worker(
    thread: QThread,
    worker: QObject,
    *,
    on_finished=None,
    on_error=None,
) -> None:
    """Wire standard lifecycle signals and start the worker thread.

    Connect any domain-specific signals (log, progress, etc.) to the worker
    BEFORE calling this function.  This wires:
      - worker → thread (moveToThread)
      - thread.started → worker.run
      - worker.finished → thread.quit + worker.deleteLater
      - worker.error   → thread.quit + worker.deleteLater
      - thread.finished → thread.deleteLater
      - optional on_finished / on_error callbacks
    """
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    worker.error.connect(thread.quit)
    worker.error.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    if on_finished is not None:
        worker.finished.connect(on_finished)
    if on_error is not None:
        worker.error.connect(on_error)
    thread.start()
