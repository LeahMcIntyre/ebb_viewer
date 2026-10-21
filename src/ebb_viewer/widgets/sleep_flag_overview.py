"""Sleep QC overview: one boxplot per flagging metric, one dot per animal.

Animals past a metric's threshold are red and labelled; clicking a dot selects
the animal and offers "Flag for Review". Each threshold is a dashed line labelled
with its value (the values live in the manifest). Dot outlines show the animal's Sleep QC status, and
excluded animals are greyed out.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ebb.process.sleep_flagging import METRIC_BY_KEY, METRICS, flagged_metrics, past_threshold

_COLS = 3
_GRAY = (110, 110, 110, 180)
_RED = (210, 70, 50, 220)
_BLUE = (50, 110, 220, 230)
_EXCLUDED = (200, 200, 200, 140)
_STATUS_PEN = {
    "ok": pg.mkPen((40, 150, 70), width=2),
    "needs_review": pg.mkPen((230, 140, 0), width=2.4),
}


class FlagOverview(QWidget):
    """Boxplot grid of the flagging metrics (see module docstring).

    Signals:
        animal_clicked(animal): a dot was clicked (``""`` when the strip is dismissed).
        flag_requested(animal): "Flag for Review" was clicked for the selected animal.
        """

    animal_clicked = pyqtSignal(str)
    flag_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._table: pd.DataFrame | None = None
        self._thresholds: dict[str, float] = {}
        self._statuses: dict[str, str | None] = {}
        self._selected: str | None = None
        self._plots: dict[str, pg.PlotItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._summary = QLabel("")
        self._summary.setStyleSheet("color: #555;")
        layout.addWidget(self._summary)

        self._grid = pg.GraphicsLayoutWidget()
        self._grid.setBackground("w")
        for i, m in enumerate(METRICS):
            p: pg.PlotItem = self._grid.addPlot(row=i // _COLS, col=i % _COLS)
            p.showGrid(x=False, y=True, alpha=0.3)
            p.setTitle(m.label, size="10pt")
            p.getAxis("bottom").setStyle(showValues=False)
            p.setMouseEnabled(x=False, y=True)
            self._plots[m.key] = p
        self._grid.setMinimumSize(560, 360)
        layout.addWidget(self._grid, stretch=1)

        self._strip = QFrame()
        self._strip.setFrameShape(QFrame.Shape.StyledPanel)
        self._strip.setStyleSheet(
            "QFrame { background: #f0f4ff; border: 1px solid #b0c4f0; border-radius: 3px; }"
        )
        row = QHBoxLayout(self._strip)
        row.setContentsMargins(10, 4, 6, 4)
        self._strip_lbl = QLabel()
        self._strip_lbl.setStyleSheet("font-weight: bold;")
        row.addWidget(self._strip_lbl)
        row.addStretch(1)
        self._btn_flag = QPushButton("Flag for Review")
        self._btn_flag.setFixedHeight(24)
        self._btn_flag.clicked.connect(self._on_flag_clicked)
        row.addWidget(self._btn_flag)
        btn_dismiss = QPushButton("×")
        btn_dismiss.setFixedSize(24, 24)
        btn_dismiss.setToolTip("Dismiss")
        btn_dismiss.clicked.connect(self._dismiss)
        row.addWidget(btn_dismiss)
        self._strip.setVisible(False)
        layout.addWidget(self._strip)

    @property
    def selected(self) -> str | None:
        """The animal whose dot is selected, if any."""
        return self._selected

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def set_data(
        self,
        table: pd.DataFrame | None,
        thresholds: dict[str, float],
        statuses: dict[str, str | None],
        selected: str | None = None,
    ) -> None:
        """Redraw every plot.

        Args:
            table: Metrics by animal (``sleep_flagging.metrics_table``), or None.
            thresholds: ``{metric key: cutoff}``.
            statuses: ``{animal: sleep_qc status}``.
            selected: Animal to highlight.
        """
        self._table = table
        self._thresholds = dict(thresholds)
        self._statuses = dict(statuses)
        self._selected = selected or None
        for m in METRICS:
            self._draw_metric(m.key)
        self._update_summary()
        if self._selected:
            self._show_strip(self._selected)
        else:
            self._strip.setVisible(False)

    def flagged_animals(self) -> dict[str, list[str]]:
        """``{animal: [metric keys past threshold]}`` for animals past at least one."""
        if self._table is None:
            return {}
        out = {}
        for animal, row in self._table.iterrows():
            keys = flagged_metrics(row.to_dict(), self._thresholds)
            if keys:
                out[str(animal)] = keys
        return out

    def _draw_metric(self, key: str) -> None:
        m = METRIC_BY_KEY[key]
        p = self._plots[key]
        p.clear()
        if self._table is None or self._table.empty:
            return
        col = self._table[key].dropna()
        if col.empty:
            return
        values = col.to_numpy(dtype=float)
        animals = np.array([str(a) for a in col.index])

        self._add_box(p, values)
        cutoff = self._thresholds.get(key)
        if m.direction is not None and cutoff is not None:
            p.addItem(
                pg.InfiniteLine(
                    pos=cutoff,
                    angle=0,
                    pen=pg.mkPen((0, 0, 0), width=1, style=Qt.PenStyle.DashLine),
                    label=f"{m.direction} {cutoff:g}",
                    labelOpts={"position": 0.97, "color": (0, 0, 0), "anchors": [(1, 1), (1, 1)]},
                )
            )
            flagged = np.array([past_threshold(v, m.direction, cutoff) for v in values])
        else:
            flagged = np.zeros(len(values), dtype=bool)

        jitter = np.random.default_rng(0).uniform(-0.18, 0.18, len(values))
        brushes, pens, sizes = [], [], []
        for a, f in zip(animals, flagged, strict=True):
            status = self._statuses.get(a)
            sel = a == self._selected
            brushes.append(
                pg.mkBrush(*_EXCLUDED)
                if status == "excluded"
                else pg.mkBrush(*(_BLUE if sel else _RED if f else _GRAY))
            )
            pens.append(_STATUS_PEN.get(status, pg.mkPen(None)))
            sizes.append(11 if sel else 8)
        sc = pg.ScatterPlotItem(
            jitter, values, data=animals, brush=brushes, pen=pens, size=sizes
        )
        sc.sigClicked.connect(self._on_dot_clicked)
        p.addItem(sc)

        font = QFont()
        font.setPointSize(7)
        for x, y, a, f in zip(jitter, values, animals, flagged, strict=True):
            if f:
                lbl = pg.TextItem(a, anchor=(0, 0.5), color=(180, 40, 20))
                lbl.setFont(font)
                lbl.setPos(x + 0.05, y)
                p.addItem(lbl)

        p.setXRange(-0.7, 1.2)
        lo, hi = float(values.min()), float(values.max())
        if cutoff is not None:
            lo, hi = min(lo, cutoff), max(hi, cutoff)
        pad = (hi - lo) * 0.08 or 1.0
        p.setYRange(lo - pad, hi + pad)

    @staticmethod
    def _add_box(p: pg.PlotItem, values: np.ndarray) -> None:
        """Tukey box-and-whisker at x = 0 (skipped below two animals)."""
        if len(values) < 2:
            return
        gray = pg.mkPen((60, 60, 60), width=1.2)
        q1, med, q3 = np.percentile(values, [25, 50, 75])
        iqr = q3 - q1
        lo_wh = values[values >= q1 - 1.5 * iqr].min()
        hi_wh = values[values <= q3 + 1.5 * iqr].max()
        w, cap = 0.3, 0.15
        p.addItem(pg.PlotCurveItem([-w, -w, w, w, -w], [q1, q3, q3, q1, q1], pen=gray))
        p.addItem(pg.PlotCurveItem([-w, w], [med, med], pen=pg.mkPen((60, 60, 60), width=2.2)))
        p.addItem(pg.PlotCurveItem([0, 0], [q1, lo_wh], pen=gray))
        p.addItem(pg.PlotCurveItem([0, 0], [q3, hi_wh], pen=gray))
        p.addItem(pg.PlotCurveItem([-cap, cap], [lo_wh, lo_wh], pen=gray))
        p.addItem(pg.PlotCurveItem([-cap, cap], [hi_wh, hi_wh], pen=gray))

    def _update_summary(self) -> None:
        if self._table is None or self._table.empty:
            self._summary.setText("No sleep metrics yet. Run Reclassify first.")
            return
        flagged = self.flagged_animals()
        waiting = [a for a in flagged if self._statuses.get(a) is None]
        self._summary.setText(
            f"{len(self._table)} animals; {len(flagged)} past a threshold "
            f"({len(waiting)} not yet flagged or reviewed). Click a dot to select an animal."
        )

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _on_dot_clicked(self, item, spots, ev) -> None:
        if len(spots) == 0:  # pyqtgraph passes an ndarray of spots
            return
        animal = str(spots[0].data())
        self._selected = animal
        self._show_strip(animal)
        self.animal_clicked.emit(animal)

    def _show_strip(self, animal: str) -> None:
        keys = self.flagged_animals().get(animal, [])
        past = ", ".join(METRIC_BY_KEY[k].label for k in keys) or "no thresholds"
        status = self._statuses.get(animal)
        tag = f" [{status.replace('_', ' ')}]" if status else ""
        self._strip_lbl.setText(f"Selected: {animal}{tag} - past: {past}")
        already = status == "needs_review"
        self._btn_flag.setEnabled(not already and status != "excluded")
        self._btn_flag.setText("Flagged for review" if already else "Flag for Review")
        self._strip.setVisible(True)

    def _on_flag_clicked(self) -> None:
        if self._selected:
            self.flag_requested.emit(self._selected)

    def _dismiss(self) -> None:
        self._selected = None
        self._strip.setVisible(False)
        self.animal_clicked.emit("")
