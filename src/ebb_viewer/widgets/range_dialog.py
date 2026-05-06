from PyQt6 import QtWidgets


class FreqBoundsDialog(QtWidgets.QDialog):
    """Modal dialog to set xRange [fmin, fmax] with validation."""

    def __init__(
        self,
        *,
        fmin: float,
        fmax: float,
        fres: float = 0.5,
        xrange=(0.5, 110),
        parent=None,
        title="Set Frequency Range Plotting Bounds",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        self.err = QtWidgets.QLabel("")
        self.err.setStyleSheet("color:#b00020;")
        self.err.setVisible(False)

        self.spin_min = QtWidgets.QDoubleSpinBox()
        self.spin_min.setRange(fmin, fmax - fres)
        self.spin_min.setSingleStep(fres)
        self.spin_min.setValue(xrange[0])

        self.spin_max = QtWidgets.QDoubleSpinBox()
        self.spin_max.setRange(fmin + fres, fmax)
        self.spin_max.setSingleStep(fres)
        self.spin_max.setValue(xrange[1])

        form = QtWidgets.QFormLayout()
        form.addRow("fmin (Hz):", self.spin_min)
        form.addRow("fmax (Hz):", self.spin_max)

        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.err)
        lay.addWidget(self.buttons)

        # live validation
        self.spin_min.valueChanged.connect(self._validate)
        self.spin_max.valueChanged.connect(self._validate)
        self._validate()

    def _validate(self):
        a = self.spin_min.value()
        b = self.spin_max.value()
        ok = a < b
        self.err.setVisible(not ok)
        self.err.setText("fmin must be strictly less than fmax.")
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def values(self) -> tuple[float, float]:
        return self.spin_min.value(), self.spin_max.value()
