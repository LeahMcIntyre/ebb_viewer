"""Dialog that requires a reason before an animal is excluded from analysis."""

from PyQt6 import QtWidgets


class ExcludeDialog(QtWidgets.QDialog):
    """Modal dialog with a required reason; Exclude stays disabled until one is typed."""

    def __init__(self, *, animal_id: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Exclude {animal_id}")
        self.setModal(True)
        self.resize(420, 220)

        prompt = QtWidgets.QLabel(
            f"Why is {animal_id} excluded? The reason is added to the animal's notes."
        )
        prompt.setWordWrap(True)
        self.edit = QtWidgets.QPlainTextEdit()
        self.edit.setPlaceholderText("Reason (required)")

        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.btn_exclude = self.buttons.addButton(
            "Exclude", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.btn_exclude.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.edit.textChanged.connect(
            lambda: self.btn_exclude.setEnabled(bool(self.edit.toPlainText().strip()))
        )

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(prompt)
        lay.addWidget(self.edit)
        lay.addWidget(self.buttons)

    def reason(self) -> str:
        return self.edit.toPlainText().strip()


def exclude_with_reason(parent, manifest, animal_id: str) -> bool:
    """Ask for a reason and exclude ``animal_id`` in ``manifest``.

    Returns False (nothing changes) if the dialog is cancelled.
    """
    dlg = ExcludeDialog(animal_id=animal_id, parent=parent)
    if not dlg.exec():
        return False
    manifest.exclude_sleep_qc(animal_id, dlg.reason())
    return True
