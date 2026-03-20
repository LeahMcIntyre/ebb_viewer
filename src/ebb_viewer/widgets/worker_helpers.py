"""Helper for launching background QThread workers."""
from PyQt6.QtCore import QObject, QThread


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
