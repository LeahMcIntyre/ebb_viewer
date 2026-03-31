# trim_pair_widget.py
from PyQt6.QtCore import pyqtSignal, pyqtSlot, QSignalBlocker
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSpinBox, QLabel

class TrimToWidget(QWidget):
    changed = pyqtSignal(int, int)  # emits (a, b) exactly as shown

    def __init__(self, parent=None, *, minimum=1, maximum=168, step=1, values=(48,72)):
        super().__init__(parent)
        self._min = int(minimum)
        self._max = int(maximum)

        self.start = QSpinBox()
        self.end   = QSpinBox()

        #Set up start and end box
        for box in (self.start, self.end):
            box.setRange(self._min, self._max)
            box.setSingleStep(step)

        or_lbl = QLabel("or")
        or_lbl.setStyleSheet("color: #666; font-size: 11px;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.start)
        lay.addWidget(or_lbl)
        lay.addWidget(self.end)

        #Set values as default value and enforce order
        self.start.setValue(int(values[0]))
        self.end.setValue(int(values[1]))

        # one tiny handler for both
        self.start.valueChanged.connect(self._on_changed)
        self.end.valueChanged.connect(self._on_changed)

    @pyqtSlot(int)  
    def _on_changed(self, _):
        self.changed.emit(self.start.value(), self.end.value())

    def value(self) -> tuple[int, int]:
        return self.start.value(), self.end.value()

    # Block start and end until both values are set
    def setValue(self, start: int, end: int) -> None:
        with QSignalBlocker(self.start), QSignalBlocker(self.end):
            self.start.setValue(int(start))
            self.end.setValue(int(end))
        # emit one combined change
        self.changed.emit(self.start.value(), self.end.value())