"""Spindle Mask view: percent of each state masked as spindle artifact, one dot per file.

Boxplot (IQR box, 1.5 x IQR whiskers) with every animal's point on top, for Wake, NREM,
REM and Total. Outliers are red and labelled; an orange ring marks animals whose
reclassification applied the EMG gate. Clicking a dot lists that animal's percentages.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

STATE_ORDER = ["Wake", "NREM", "REM", "Total"]
_GRAY = (110, 110, 110, 180)
_RED = (210, 70, 50, 210)
_GATE_PEN = pg.mkPen((230, 140, 0), width=2.2)


def animal_percent_text(df: pd.DataFrame, animal: str) -> str:
    """``"Wake 12.3% · NREM 4.5% · REM 1.0% · Total 6.7%"`` for one animal (n/a when empty)."""
    parts = []
    for state in STATE_ORDER:
        row = df[(df["mouse_id"] == animal) & (df["state"] == state)]
        frac = row["fraction"].iloc[0] if len(row) else float("nan")
        parts.append(f"{state} {frac * 100:.1f}%" if pd.notna(frac) else f"{state} n/a")
    return " · ".join(parts)


class SpindleFractionPlot(QWidget):
    """Box-and-strip chart of the percent of each state masked by spindle artifact."""

    animal_clicked = pyqtSignal(str)  # "" when the selection is dismissed

    def __init__(self, parent=None):
        super().__init__(parent)
        self._df: pd.DataFrame | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._pw = pg.PlotWidget(background="w")
        self._pw.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        pi = self._pw.getPlotItem()
        pi.showGrid(x=False, y=True, alpha=0.3)
        pi.setLabel("left", "Epochs masked by spindle artifact (%)")
        pi.getAxis("left").enableAutoSIPrefix(False)
        pi.getAxis("bottom").setStyle(tickTextOffset=8)
        layout.addWidget(self._pw)

        # Selection strip (hidden until a dot is clicked).
        self._strip = QFrame()
        self._strip.setFrameShape(QFrame.Shape.StyledPanel)
        self._strip.setStyleSheet(
            "QFrame { background: #f0f4ff; border: 1px solid #b0c4f0; border-radius: 3px; }"
        )
        strip_row = QHBoxLayout(self._strip)
        strip_row.setContentsMargins(10, 4, 6, 4)
        self._strip_lbl = QLabel()
        self._strip_lbl.setStyleSheet("font-weight: bold; border: none;")
        strip_row.addWidget(self._strip_lbl, 1)
        btn_dismiss = QPushButton("×")
        btn_dismiss.setFixedSize(24, 24)
        btn_dismiss.setToolTip("Dismiss")
        btn_dismiss.clicked.connect(self._dismiss)
        strip_row.addWidget(btn_dismiss)
        self._strip.setVisible(False)
        layout.addWidget(self._strip)

    def set_data(
        self,
        df: pd.DataFrame | None,
        title: str = "",
        selected: str | None = None,
        gated: set[str] | None = None,
    ) -> None:
        """Draw ``df`` (columns mouse_id, state, fraction; fractions 0-1, shown as percent)."""
        self._df = df
        gated = gated or set()
        pi = self._pw.getPlotItem()
        pi.clear()
        pi.setTitle(title, size="11pt")
        pi.getAxis("bottom").setTicks([list(enumerate(STATE_ORDER))])
        if df is None or df.empty:
            return

        rng = np.random.default_rng(42)  # reproducible jitter
        box_w, cap_w = 0.22, 0.12
        line = pg.mkPen((60, 60, 60), width=1.2)
        thick = pg.mkPen((60, 60, 60), width=2.2)
        label_font = QFont()
        label_font.setPointSize(7)
        y_max = 0.0

        for xi, state in enumerate(STATE_ORDER):
            sdf = df[df["state"] == state].dropna(subset=["fraction"])
            if sdf.empty:
                continue
            pct = sdf["fraction"].to_numpy(dtype=float) * 100
            mids = sdf["mouse_id"].to_numpy()
            y_max = max(y_max, float(pct.max()))

            is_out = np.zeros(len(pct), dtype=bool)
            med = float(np.median(pct))
            if len(pct) >= 2:  # a box needs at least two points
                q1, med, q3 = np.percentile(pct, [25, 50, 75])
                lo_fence, hi_fence = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
                lo_wh = pct[pct >= lo_fence].min()
                hi_wh = pct[pct <= hi_fence].max()
                for xs, ys, pen in (
                    (
                        [xi - box_w, xi - box_w, xi + box_w, xi + box_w, xi - box_w],
                        [q1, q3, q3, q1, q1],
                        line,
                    ),
                    ([xi - box_w, xi + box_w], [med, med], thick),
                    ([xi, xi], [q1, lo_wh], line),
                    ([xi, xi], [q3, hi_wh], line),
                    ([xi - cap_w, xi + cap_w], [lo_wh, lo_wh], line),
                    ([xi - cap_w, xi + cap_w], [hi_wh, hi_wh], line),
                ):
                    pi.addItem(pg.PlotCurveItem(xs, ys, pen=pen))
                is_out = (pct < lo_fence) | (pct > hi_fence)

            xs = xi + rng.uniform(-0.14, 0.14, len(pct))
            is_sel = mids == selected
            for mask, brush, size in (
                (~is_out & ~is_sel, pg.mkBrush(*_GRAY), 7),
                (is_out & ~is_sel, pg.mkBrush(*_RED), 7),
                (is_sel, pg.mkBrush(50, 110, 220, 230), 10),
            ):
                if not mask.any():
                    continue
                sc = pg.ScatterPlotItem(
                    xs[mask],
                    pct[mask],
                    data=mids[mask],
                    pen=[_GATE_PEN if m in gated else pg.mkPen(None) for m in mids[mask]],
                    brush=brush,
                    size=size,
                )
                sc.sigClicked.connect(self._on_dot_clicked)
                pi.addItem(sc)
            for x_pt, y_pt, mid in zip(xs[is_out], pct[is_out], mids[is_out], strict=True):
                lbl = pg.TextItem(
                    mid, anchor=(0.5, 1.2) if y_pt > med else (0.5, -0.2), color=(180, 40, 20)
                )
                lbl.setFont(label_font)
                lbl.setPos(x_pt, y_pt)
                pi.addItem(lbl)

        pi.setXRange(-0.6, len(STATE_ORDER) - 0.4)
        pi.setYRange(0, min(100.0, y_max * 1.15 + 1.0) if y_max > 0 else 50.0)

    def _on_dot_clicked(self, item, spots, ev) -> None:
        if not spots or self._df is None:
            return
        animal = str(spots[0].data())
        self._strip_lbl.setText(f"{animal}: {animal_percent_text(self._df, animal)}")
        self._strip.setVisible(True)
        self.animal_clicked.emit(animal)

    def clear_selection(self) -> None:
        """Hide the selection strip without emitting."""
        self._strip.setVisible(False)

    def _dismiss(self) -> None:
        self.clear_selection()
        self.animal_clicked.emit("")
