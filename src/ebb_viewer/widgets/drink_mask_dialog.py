from PyQt6 import QtWidgets


class DrinkMaskDialogue(QtWidgets.QDialog):
    """Modal dialog to set drink mask offset and pad."""

    def __init__(
        self,
        *,
        drink_path: str,
        offset_val: float = 0.0,
        pad: int = 0,
        parent=None,
        title="Drink Mask Confirmation",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        self.msg = QtWidgets.QLabel(f"Confirm drink mask settings for {drink_path}:")

        self.pad_sec = QtWidgets.QSpinBox()
        self.pad_sec.setRange(0, 10)
        self.pad_sec.setValue(pad)
        self.pad_sec.setToolTip(
            "Amount of seconds drinking events will be padded with on both sides."
        )

        self.offset = QtWidgets.QDoubleSpinBox()
        self.offset.setRange(0, 60)
        self.offset.setSingleStep(0.01)
        self.offset.setValue(offset_val)
        self.offset.setToolTip(
            "In seconds, the delay between the start of the EEG recording and the start of the video."
        )

        form = QtWidgets.QFormLayout()
        form.addRow("Pad Seconds (s):", self.pad_sec)
        form.addRow("Video Offset (s):", self.offset)

        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.msg)
        lay.addLayout(form)
        lay.addWidget(self.buttons)

    def values(self) -> tuple[int, float]:
        return self.pad_sec.value(), self.offset.value()
