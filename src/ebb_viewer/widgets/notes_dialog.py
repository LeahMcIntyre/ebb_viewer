"""Modal dialog for editing free-text notes on an animal."""

from PyQt6 import QtWidgets


class NotesDialog(QtWidgets.QDialog):
    """Modal dialog with a multi-line text editor for one animal's notes."""

    def __init__(self, *, animal_id: str, initial_text: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Notes — {animal_id}")
        self.setModal(True)
        self.resize(420, 280)

        self.edit = QtWidgets.QPlainTextEdit()
        self.edit.setPlainText(initial_text)

        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.edit)
        lay.addWidget(self.buttons)

    def text(self) -> str:
        return self.edit.toPlainText()
