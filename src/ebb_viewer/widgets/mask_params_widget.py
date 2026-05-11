"""Widget for editing mask + filter parameters in the Export Masks page.

Currently used only by `pages/export_masks.py`. The PSD compute page
(`pages/psds.py`) keeps its own `MaskingSettingsDialog` — unifying the
two is tracked as a Phase 3 cleanup TODO.

The widget owns its UI state and exposes:
- :meth:`to_params` — current values as a JSON-serializable dict
- :meth:`from_params` — load values from a previously-saved dict
- ``changed`` signal — emitted on any user-visible change (for "modified" UI)

Sections (each wrapped in its own ``QGroupBox``):
- States
- SD mask
- Spindle noise threshold
- SWD mask + pad
- Annotation mask
- Hour windows (clock-time filter)
- Drink mask + pad + auto-detected offset CSV display
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ebb.process.state_presets import (
    CANONICAL_ORDER,
    DEFAULT_STATES,
    PRESET_DESCRIPTIONS,
    PRESET_DISPLAY,
)
from ebb_viewer.widgets.collapsible_section import CollapsibleSection

# Defaults mirror estimate_psd's signature so a freshly-constructed widget
# matches the PSD pipeline's untouched behavior.
_DEFAULT_NOISE_THRESH = 0.5
_DEFAULT_WINSIZE_S = 180
_DEFAULT_RADIUS_S = 0.5
_DEFAULT_NSTD = 5.0
_DEFAULT_DRINK_PAD_S = 2
_DEFAULT_SWD_PAD_S = 0


class MaskParamsWidget(QWidget):
    """Self-contained editor for mask + filter parameters.

    Args:
        project_root: Used for "Browse…" dialogs to start in a sensible
            location. May be None when the widget is constructed before a
            project is selected; setters use the cwd in that case.
        swd_available: If False, the SWD "Mask out SWDs" radio is disabled
            and the section shows a hint about how to enable it.
    """

    changed = pyqtSignal()

    def __init__(
        self,
        project_root: Path | None = None,
        parent: QWidget | None = None,
        *,
        swd_available: bool = False,
    ):
        super().__init__(parent)
        self._project_root = Path(project_root) if project_root else None
        self._swd_available = swd_available
        self._ann_dir: Path | None = None

        self._build_ui()
        self._wire()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def to_params(self) -> dict:
        """Return current values as a JSON-serializable dict."""
        states = [k for k, cb in self._state_boxes.items() if cb.isChecked()]
        hw_enabled = self.chk_hour_window.isChecked()
        days_specific = self._radio_hw_sel.isChecked()
        return {
            "states": states,
            "nstd": float(self.dspin_z.value()),
            "winsize": int(self.spin_window.value()),
            "radius": float(self.dspin_radius.value()),
            "noise_thresh": float(self.dspin_noise.value()),
            "use_swd_mask": self._radio_swd_mask.isChecked(),
            "swd_pad": int(self.spin_swd_pad.value()),
            "ann_enabled": self.chk_ann.isChecked(),
            "ann_dir": str(self._ann_dir) if self._ann_dir else None,
            "ann_keywords": self._ann_keyword_edit.text().strip(),
            "ann_match_mode": "exact" if self._radio_ann_exact.isChecked() else "contains",
            "ann_pad_before": float(self._ann_pad_before.value()),
            "ann_pad_after": float(self._ann_pad_after.value()),
            "hw_enabled": hw_enabled,
            "hour_windows": self._get_defined_windows() if hw_enabled else None,
            "selected_days": (
                self._parse_days_field() if hw_enabled and days_specific else None
            ),
            "use_drink_mask": self.chk_use_drink.isChecked(),
            "drink_pad": int(self.spin_drink_pad.value()),
        }

    def from_params(self, params: dict) -> None:
        """Populate widgets from a saved params dict (missing keys → defaults)."""
        # Block all change signals during bulk update to avoid spurious `changed`.
        with _block_signals(self._all_signal_sources()):
            # States
            saved_states = params.get("states") or list(DEFAULT_STATES)
            for key, cb in self._state_boxes.items():
                cb.setChecked(key in saved_states)

            # SD mask
            self.dspin_z.setValue(float(params.get("nstd", _DEFAULT_NSTD)))
            self.spin_window.setValue(int(params.get("winsize", _DEFAULT_WINSIZE_S)))
            self.dspin_radius.setValue(float(params.get("radius", _DEFAULT_RADIUS_S)))

            # Spindle noise
            self.dspin_noise.setValue(float(params.get("noise_thresh", _DEFAULT_NOISE_THRESH)))

            # SWD — also tolerate legacy psd_params.json shape that used swd_mode.
            if "use_swd_mask" in params:
                swd_on = bool(params["use_swd_mask"])
            else:
                swd_on = params.get("swd_mode") == "mask_out"
            if swd_on and self._swd_available:
                self._radio_swd_mask.setChecked(True)
            else:
                self._radio_swd_none.setChecked(True)
            self.spin_swd_pad.setValue(int(params.get("swd_pad", _DEFAULT_SWD_PAD_S)))

            # Annotation
            ann_dir = params.get("ann_dir")
            if ann_dir and Path(ann_dir).is_dir():
                self._ann_dir = Path(ann_dir)
                self.lbl_ann_dir.setText(str(self._ann_dir))
            else:
                self._ann_dir = None
                self.lbl_ann_dir.setText("")
            self._ann_keyword_edit.setText(params.get("ann_keywords") or "")
            if params.get("ann_match_mode") == "exact":
                self._radio_ann_exact.setChecked(True)
            else:
                self._radio_ann_contains.setChecked(True)
            self._ann_pad_before.setValue(float(params.get("ann_pad_before", 0.0)))
            self._ann_pad_after.setValue(float(params.get("ann_pad_after", 0.0)))
            self.chk_ann.setChecked(bool(params.get("ann_enabled", False)))
            self._ann_body.setEnabled(self.chk_ann.isChecked())

            # Hour windows
            self._clear_window_rows()
            windows = params.get("hour_windows") or []
            for hw in windows:
                self._add_window_row(float(hw[0]), float(hw[1]))
            selected_days = params.get("selected_days")
            if selected_days is not None:
                self._radio_hw_sel.setChecked(True)
                self._hw_days_edit.setText(",".join(str(d) for d in selected_days))
                self._hw_days_edit.setEnabled(True)
            else:
                self._radio_hw_all.setChecked(True)
                self._hw_days_edit.setEnabled(False)
            self.chk_hour_window.setChecked(bool(params.get("hw_enabled", False)))
            self._hw_body.setEnabled(self.chk_hour_window.isChecked())

            # Drink mask
            self.chk_use_drink.setChecked(bool(params.get("use_drink_mask", True)))
            self.spin_drink_pad.setValue(int(params.get("drink_pad", _DEFAULT_DRINK_PAD_S)))
            self._refresh_offset_csv_label()

        self.changed.emit()

    def set_swd_available(self, available: bool) -> None:
        """Update SWD availability after construction (e.g. once project is loaded)."""
        self._swd_available = available
        self._radio_swd_mask.setEnabled(available)
        if not available and self._radio_swd_mask.isChecked():
            self._radio_swd_none.setChecked(True)

    def set_project_root(self, project_root: Path | None) -> None:
        """Update project_root after construction; refreshes auto-detected drink offset CSV."""
        self._project_root = Path(project_root) if project_root else None
        self._refresh_offset_csv_label()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # Always-expanded sections — these are the routine knobs for every export.
        root.addWidget(CollapsibleSection("States to Compute", self._build_states_group(), collapsed=False))
        root.addWidget(CollapsibleSection(
            "Standard Deviation Mask (applied only to wake)",
            self._build_sd_group(),
            collapsed=False,
        ))
        root.addWidget(CollapsibleSection(
            "Spindle Noise Mask (applied to all states)",
            self._build_spindle_group(),
            collapsed=False,
        ))
        root.addWidget(CollapsibleSection(
            "Drink Mask",
            self._build_drink_group(),
            collapsed=False,
        ))

        # Optional sections — disabled bodies by default; start collapsed to
        # save scroll space.
        root.addWidget(CollapsibleSection("SWD Mask", self._build_swd_group(), collapsed=True))
        root.addWidget(CollapsibleSection(
            "Annotation Mask", self._build_annotation_group(), collapsed=True
        ))
        root.addWidget(CollapsibleSection(
            "Compute Hours", self._build_hour_window_group(), collapsed=True
        ))

    def _build_states_group(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 4, 8, 8)
        hint = QLabel(
            "Select one or more state groups. A separate PSD is computed for each "
            "checked group; lumped groups combine their underlying epochs."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555; font-size: 11px;")
        v.addWidget(hint)

        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        self._state_boxes: dict[str, QCheckBox] = {}
        for idx, key in enumerate(CANONICAL_ORDER):
            cb = QCheckBox(PRESET_DISPLAY[key])
            cb.setChecked(key in DEFAULT_STATES)
            cb.setToolTip(PRESET_DESCRIPTIONS[key])
            self._state_boxes[key] = cb
            r, c = divmod(idx, 3)
            grid.addWidget(cb, r, c)
        v.addLayout(grid)
        return w

    def _build_sd_group(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(8, 4, 8, 8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.spin_window = QSpinBox()
        self.spin_window.setRange(1, 6000)
        self.spin_window.setSuffix(" s")
        self.spin_window.setValue(_DEFAULT_WINSIZE_S)

        self.dspin_radius = QDoubleSpinBox()
        # 2 decimals so saved values like 0.75 don't silently round to 0.8.
        self.dspin_radius.setDecimals(2)
        self.dspin_radius.setSingleStep(0.05)
        self.dspin_radius.setRange(0.0, 60.0)
        self.dspin_radius.setSuffix(" s")
        self.dspin_radius.setValue(_DEFAULT_RADIUS_S)

        self.dspin_z = QDoubleSpinBox()
        self.dspin_z.setDecimals(2)
        self.dspin_z.setRange(1.0, 20.0)
        self.dspin_z.setSuffix(" σ")
        self.dspin_z.setValue(_DEFAULT_NSTD)

        form.addRow("Window:", self.spin_window)
        form.addRow("Radius:", self.dspin_radius)
        form.addRow("Z-threshold:", self.dspin_z)
        return w

    def _build_spindle_group(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(8, 4, 8, 8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.dspin_noise = QDoubleSpinBox()
        self.dspin_noise.setDecimals(2)
        self.dspin_noise.setRange(0.0, 1.0)
        self.dspin_noise.setSingleStep(0.05)
        self.dspin_noise.setValue(_DEFAULT_NOISE_THRESH)
        form.addRow("Spindle Noise Threshold:", self.dspin_noise)
        return w

    def _build_swd_group(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 4, 8, 8)
        self._swd_grp = QButtonGroup(self)
        self._radio_swd_none = QRadioButton("No SWD mask")
        self._radio_swd_none.setChecked(True)
        self._radio_swd_mask = QRadioButton("Mask out SWDs")
        self._radio_swd_mask.setEnabled(self._swd_available)
        self._swd_grp.addButton(self._radio_swd_none, 0)
        self._swd_grp.addButton(self._radio_swd_mask, 1)
        v.addWidget(self._radio_swd_none)
        v.addWidget(self._radio_swd_mask)

        pad_form = QFormLayout()
        pad_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.spin_swd_pad = QSpinBox()
        self.spin_swd_pad.setRange(0, 600)
        self.spin_swd_pad.setSuffix(" s")
        self.spin_swd_pad.setValue(_DEFAULT_SWD_PAD_S)
        pad_form.addRow("Pad each event:", self.spin_swd_pad)
        v.addLayout(pad_form)

        hint = QLabel(
            "Place one .mat file of SWD timestamps per animal in a swd/ folder "
            "in the project root (e.g. project/swd/AnimalID_*.mat)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 10px; color: #777; padding-left: 4px;")
        v.addWidget(hint)
        return w

    def _build_annotation_group(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 4, 8, 8)
        self.chk_ann = QCheckBox("Apply annotation mask")
        v.addWidget(self.chk_ann)

        self._ann_body = QWidget()
        self._ann_body.setEnabled(False)
        body = QVBoxLayout(self._ann_body)
        body.setContentsMargins(0, 4, 0, 0)
        body.setSpacing(6)

        dir_row = QHBoxLayout()
        self.lbl_ann_dir = QLineEdit()
        self.lbl_ann_dir.setReadOnly(True)
        self.lbl_ann_dir.setPlaceholderText("No directory selected")
        self.btn_ann_dir = QPushButton("Browse…")
        dir_row.addWidget(QLabel("Annotation directory:"))
        dir_row.addWidget(self.lbl_ann_dir, 1)
        dir_row.addWidget(self.btn_ann_dir)
        body.addLayout(dir_row)

        kw_form = QFormLayout()
        kw_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._ann_keyword_edit = QLineEdit()
        self._ann_keyword_edit.setPlaceholderText("e.g.  drink, artifact")
        kw_form.addRow("Keywords:", self._ann_keyword_edit)
        body.addLayout(kw_form)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Match mode:"))
        self._radio_ann_contains = QRadioButton("Contains")
        self._radio_ann_exact = QRadioButton("Exact")
        self._radio_ann_contains.setChecked(True)
        self._ann_mode_grp = QButtonGroup(self)
        self._ann_mode_grp.addButton(self._radio_ann_contains, 0)
        self._ann_mode_grp.addButton(self._radio_ann_exact, 1)
        mode_row.addWidget(self._radio_ann_contains)
        mode_row.addWidget(self._radio_ann_exact)
        mode_row.addStretch()
        body.addLayout(mode_row)

        pad_form = QFormLayout()
        pad_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._ann_pad_before = QDoubleSpinBox()
        self._ann_pad_before.setRange(0.0, 3600.0)
        self._ann_pad_before.setSingleStep(1.0)
        self._ann_pad_before.setDecimals(1)
        self._ann_pad_before.setSuffix(" s")
        self._ann_pad_after = QDoubleSpinBox()
        self._ann_pad_after.setRange(0.0, 3600.0)
        self._ann_pad_after.setSingleStep(1.0)
        self._ann_pad_after.setDecimals(1)
        self._ann_pad_after.setSuffix(" s")
        pad_form.addRow("Pad before:", self._ann_pad_before)
        pad_form.addRow("Pad after:", self._ann_pad_after)
        body.addLayout(pad_form)

        v.addWidget(self._ann_body)
        return w

    def _build_hour_window_group(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 4, 8, 8)
        self.chk_hour_window = QCheckBox("Restrict to clock-time window")
        v.addWidget(self.chk_hour_window)

        self._hw_body = QWidget()
        self._hw_body.setEnabled(False)
        body = QVBoxLayout(self._hw_body)
        body.setContentsMargins(0, 4, 0, 0)
        body.setSpacing(6)

        self._hw_windows_widget = QWidget()
        self._hw_windows_layout = QVBoxLayout(self._hw_windows_widget)
        self._hw_windows_layout.setContentsMargins(0, 0, 0, 0)
        self._hw_windows_layout.setSpacing(2)
        body.addWidget(self._hw_windows_widget)

        add_row = QHBoxLayout()
        self.spin_add_start = QSpinBox()
        self.spin_add_start.setRange(0, 23)
        self.spin_add_start.setSuffix(" h")
        self.spin_add_end = QSpinBox()
        self.spin_add_end.setRange(0, 23)
        self.spin_add_end.setSuffix(" h")
        self.spin_add_end.setValue(1)
        self.btn_add_window = QPushButton("Add")
        self.btn_add_window.setFixedWidth(48)
        add_row.addWidget(self.spin_add_start)
        add_row.addWidget(QLabel("–"))
        add_row.addWidget(self.spin_add_end)
        add_row.addWidget(self.btn_add_window)
        add_row.addStretch()
        body.addLayout(add_row)

        wrap_hint = QLabel(
            "If end < start the window wraps midnight (e.g. 20–6 = dark phase)."
        )
        wrap_hint.setWordWrap(True)
        wrap_hint.setStyleSheet("font-size: 10px; color: #777; padding-left: 4px;")
        body.addWidget(wrap_hint)

        day_row = QHBoxLayout()
        self._radio_hw_all = QRadioButton("All days")
        self._radio_hw_all.setChecked(True)
        self._radio_hw_sel = QRadioButton("Specific days:")
        self._hw_day_grp = QButtonGroup(self)
        self._hw_day_grp.addButton(self._radio_hw_all, 0)
        self._hw_day_grp.addButton(self._radio_hw_sel, 1)
        self._hw_days_edit = QLineEdit()
        self._hw_days_edit.setPlaceholderText("0,1,2  (0 = recording start date)")
        self._hw_days_edit.setEnabled(False)
        day_row.addWidget(self._radio_hw_all)
        day_row.addWidget(self._radio_hw_sel)
        day_row.addWidget(self._hw_days_edit, 1)
        body.addLayout(day_row)

        v.addWidget(self._hw_body)
        return w

    def _build_drink_group(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 4, 8, 8)
        self.chk_use_drink = QCheckBox("Apply drink mask when available")
        self.chk_use_drink.setChecked(True)
        v.addWidget(self.chk_use_drink)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.spin_drink_pad = QSpinBox()
        self.spin_drink_pad.setRange(0, 600)
        self.spin_drink_pad.setSuffix(" s")
        self.spin_drink_pad.setValue(_DEFAULT_DRINK_PAD_S)
        form.addRow("Pad each event:", self.spin_drink_pad)
        v.addLayout(form)

        # Auto-detected offset CSV: read-only display, no override.
        offset_row = QHBoxLayout()
        offset_row.addWidget(QLabel("Offset CSV:"))
        self.lbl_offset_csv = QLineEdit()
        self.lbl_offset_csv.setReadOnly(True)
        self.lbl_offset_csv.setPlaceholderText("(none — using zero offset)")
        offset_row.addWidget(self.lbl_offset_csv, 1)
        v.addLayout(offset_row)

        hint = QLabel(
            "Place a single CSV with per-animal video offsets in project/drink_masks/. "
            "The widget auto-detects it; multiple CSVs are an error (see Export Masks docs)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 10px; color: #777; padding-left: 4px;")
        v.addWidget(hint)

        self._refresh_offset_csv_label()
        return w

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def _wire(self) -> None:
        for cb in self._state_boxes.values():
            cb.toggled.connect(self._emit_changed)
        for spin in (
            self.spin_window,
            self.dspin_radius,
            self.dspin_z,
            self.dspin_noise,
            self.spin_swd_pad,
            self._ann_pad_before,
            self._ann_pad_after,
            self.spin_drink_pad,
        ):
            spin.valueChanged.connect(self._emit_changed)

        self._radio_swd_none.toggled.connect(self._emit_changed)
        self._radio_swd_mask.toggled.connect(self._emit_changed)

        self.chk_ann.toggled.connect(lambda checked: self._ann_body.setEnabled(checked))
        self.chk_ann.toggled.connect(self._emit_changed)
        self.btn_ann_dir.clicked.connect(self._choose_ann_dir)
        self._ann_keyword_edit.textChanged.connect(self._emit_changed)
        self._radio_ann_contains.toggled.connect(self._emit_changed)

        self.chk_hour_window.toggled.connect(lambda checked: self._hw_body.setEnabled(checked))
        self.chk_hour_window.toggled.connect(self._emit_changed)
        self._radio_hw_all.toggled.connect(
            lambda checked: self._hw_days_edit.setEnabled(not checked)
        )
        self._radio_hw_all.toggled.connect(self._emit_changed)
        self._hw_days_edit.textChanged.connect(self._emit_changed)
        self.btn_add_window.clicked.connect(self._on_add_window_clicked)

        self.chk_use_drink.toggled.connect(self._emit_changed)

    def _emit_changed(self, *_args) -> None:
        self.changed.emit()

    def _all_signal_sources(self) -> list:
        """Widgets whose signals must be blocked during bulk from_params updates."""
        sources = list(self._state_boxes.values()) + [
            self.spin_window,
            self.dspin_radius,
            self.dspin_z,
            self.dspin_noise,
            self.spin_swd_pad,
            self._radio_swd_none,
            self._radio_swd_mask,
            self.chk_ann,
            self._ann_keyword_edit,
            self._radio_ann_contains,
            self._radio_ann_exact,
            self._ann_pad_before,
            self._ann_pad_after,
            self.chk_hour_window,
            self._radio_hw_all,
            self._radio_hw_sel,
            self._hw_days_edit,
            self.chk_use_drink,
            self.spin_drink_pad,
        ]
        return sources

    # ------------------------------------------------------------------
    # Annotation handlers
    # ------------------------------------------------------------------

    def _choose_ann_dir(self) -> None:
        start = str(self._project_root) if self._project_root else ""
        chosen = QFileDialog.getExistingDirectory(self, "Select annotation directory", start)
        if chosen:
            self._ann_dir = Path(chosen)
            self.lbl_ann_dir.setText(str(self._ann_dir))
            self.changed.emit()

    # ------------------------------------------------------------------
    # Hour window handlers
    # ------------------------------------------------------------------

    def _on_add_window_clicked(self) -> None:
        self._add_window_row(float(self.spin_add_start.value()), float(self.spin_add_end.value()))
        self.changed.emit()

    def _add_window_row(self, hour_start: float, hour_end: float) -> None:
        row = QWidget()
        row.setProperty("hw_start", hour_start)
        row.setProperty("hw_end", hour_end)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(QLabel(f"{int(hour_start)} h – {int(hour_end)} h"))
        hl.addStretch()
        btn = QPushButton("×")
        btn.setFixedWidth(24)
        btn.clicked.connect(lambda: self._remove_window_row(row))
        hl.addWidget(btn)
        self._hw_windows_layout.addWidget(row)

    def _remove_window_row(self, row: QWidget) -> None:
        self._hw_windows_layout.removeWidget(row)
        row.deleteLater()
        self.changed.emit()

    def _clear_window_rows(self) -> None:
        while self._hw_windows_layout.count():
            item = self._hw_windows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _get_defined_windows(self) -> list[tuple[float, float]]:
        windows = []
        for i in range(self._hw_windows_layout.count()):
            row = self._hw_windows_layout.itemAt(i).widget()
            if row is not None:
                windows.append((row.property("hw_start"), row.property("hw_end")))
        return windows

    def _parse_days_field(self) -> list[int] | None:
        raw = self._hw_days_edit.text().strip()
        if not raw:
            return None
        try:
            return [int(x) for x in raw.split(",") if x.strip()]
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Drink mask handlers
    # ------------------------------------------------------------------

    def _refresh_offset_csv_label(self) -> None:
        """Display the auto-detected offset CSV (if a single one exists in drink_masks/)."""
        auto = self._auto_offset_csv()
        self.lbl_offset_csv.setText(str(auto) if auto is not None else "")

    def _auto_offset_csv(self) -> Path | None:
        if self._project_root is None:
            return None
        drink_dir = self._project_root / "drink_masks"
        if not drink_dir.is_dir():
            return None
        matches = sorted(drink_dir.glob("*.csv"))
        return matches[0] if len(matches) == 1 else None


class _block_signals:
    """Context manager: block signals on a list of widgets for the block's duration."""

    def __init__(self, widgets: list):
        self._widgets = widgets

    def __enter__(self):
        for w in self._widgets:
            w.blockSignals(True)
        return self

    def __exit__(self, *exc):
        for w in self._widgets:
            w.blockSignals(False)
