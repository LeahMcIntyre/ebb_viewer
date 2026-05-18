"""Finalize page — seal completed PSD runs into psds_final.pkl.

One card per PSD run; each shows pending-review counts and the source pkl
that will be used. The Finalize button is enabled only when zero animals
are pending review and a merged source pkl exists. Settings… opens a
read-only summary of the run's saved psd_params.json.
"""

import pickle
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ebb.core.naming import parse_animal_id
from ebb.process.state_presets import PRESET_DISPLAY
from ebb_viewer.pipeline import psd_params
from ebb_viewer.pipeline.manifest import Manifest

CH_LABELS = ["LFC", "RSC", "LSC"]


class _RunSettingsDialog(QDialog):
    """Read-only display of psd_params.json for a single run."""

    def __init__(self, parent, *, run_name: str, run_dir: Path, params: dict, manifest: Manifest):
        super().__init__(parent)
        self.setWindowTitle(f"Settings — {run_name}")
        self.setMinimumWidth(420)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._run_dir = run_dir

        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── General PSD settings ──────────────────────────────────────────
        gb_gen = QGroupBox("General PSD Settings")
        f = QFormLayout(gb_gen)
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        ch_indices = params.get("channels", [])
        ch_names = [CH_LABELS[i] for i in ch_indices if i < len(CH_LABELS)]
        state_keys = psd_params.states_from_params(params)
        state_names = ", ".join(PRESET_DISPLAY.get(k, k) for k in state_keys)
        f.addRow("Channels:", QLabel(", ".join(ch_names) if ch_names else "—"))
        f.addRow("States:", QLabel(state_names or "—"))
        f.addRow("Sampling freq:", QLabel(f"{params.get('fs', '—')} Hz"))
        f.addRow("Commutator thr:", QLabel(f"{params.get('comm_value', '—')} µV"))
        f.addRow("SD window:", QLabel(f"{params.get('winsize', '—')} s"))
        f.addRow("SD radius:", QLabel(f"{params.get('radius', '—')} s"))
        f.addRow("SD z-threshold:", QLabel(str(params.get("nstd", "—"))))
        f.addRow("Spindle noise thr:", QLabel(str(params.get("noise_thresh", "—"))))
        root.addWidget(gb_gen)

        # ── Hour windows ──────────────────────────────────────────────────
        gb_hw = QGroupBox("Hour Windows")
        f2 = QFormLayout(gb_hw)
        f2.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        if params.get("hw_enabled"):
            windows = params.get("hour_windows") or []
            wins_str = ", ".join(f"{int(w[0])}–{int(w[1])}h" for w in windows) or "—"
            days = params.get("selected_days")
            day_str = "all days" if days is None else f"days {', '.join(str(d) for d in days)}"
            f2.addRow("Windows:", QLabel(wins_str))
            f2.addRow("Days:", QLabel(day_str))
        else:
            lbl = QLabel("Off (all hours included)")
            lbl.setStyleSheet("color: gray;")
            f2.addRow("Status:", lbl)
        root.addWidget(gb_hw)

        # ── SWD mask ─────────────────────────────────────────────────────
        gb_swd = QGroupBox("SWD Mask")
        f3 = QFormLayout(gb_swd)
        f3.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        swd_mode = params.get("swd_mode", "none")
        if swd_mode == "mask_out":
            lbl = QLabel("Enabled — SWDs masked out")
            lbl.setStyleSheet("color: #1a5c8a;")
        else:
            lbl = QLabel("Off")
            lbl.setStyleSheet("color: gray;")
        f3.addRow("Mode:", lbl)
        root.addWidget(gb_swd)

        # ── Drink mask ────────────────────────────────────────────────────
        gb_drink = QGroupBox("Drink Mask")
        f4 = QFormLayout(gb_drink)
        f4.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        drink_pkl = self._run_dir / "psds_drink.pkl"
        if drink_pkl.exists():
            try:
                with open(drink_pkl, "rb") as f:
                    drink_records = pickle.load(f)
                animal_ids = sorted({parse_animal_id(r["path"]) for r in drink_records})
                lbl = QLabel(f"Applied — {', '.join(animal_ids)}")
                lbl.setWordWrap(True)
                lbl.setStyleSheet("color: #1a5c8a;")
            except Exception:
                lbl = QLabel("Applied (psds_drink.pkl present)")
                lbl.setStyleSheet("color: #1a5c8a;")
        else:
            lbl = QLabel("Not used")
            lbl.setStyleSheet("color: gray;")
        f4.addRow("Status:", lbl)
        root.addWidget(gb_drink)

        # ── Annotation mask ───────────────────────────────────────────────
        gb_ann = QGroupBox("Annotation Mask")
        f5 = QFormLayout(gb_ann)
        f5.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        if params.get("ann_enabled"):
            f5.addRow("Directory:", QLabel(str(params.get("ann_dir", "—"))))
            f5.addRow("Keywords:", QLabel(str(params.get("ann_keywords", "—"))))
            f5.addRow("Match mode:", QLabel(str(params.get("ann_match_mode", "—"))))
            f5.addRow("Pad before:", QLabel(f"{params.get('ann_pad_before', 0)} s"))
            f5.addRow("Pad after:", QLabel(f"{params.get('ann_pad_after', 0)} s"))
        else:
            lbl = QLabel("Off")
            lbl.setStyleSheet("color: gray;")
            f5.addRow("Status:", lbl)
        root.addWidget(gb_ann)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)


class FinalizePage(QWidget):
    navigate_to = pyqtSignal(str)

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()

    def _poll(self):
        self._refresh()

    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        lbl = QLabel("Finalize PSD")
        lbl.setStyleSheet("font-weight: bold; font-size: 15px;")
        hdr.addWidget(lbl)
        hdr.addStretch(1)
        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.clicked.connect(self._refresh)
        hdr.addWidget(self._btn_refresh)
        root.addLayout(hdr)

        desc = QLabel(
            "Review the status of each PSD run and seal completed runs into "
            "psds_final.pkl. A run is ready to finalize when all animals have "
            "been reviewed (OK or drink mask verified)."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        root.addWidget(desc)

        # Scroll area holds the per-run cards
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cards_widget = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch(1)
        self._scroll.setWidget(self._cards_widget)
        root.addWidget(self._scroll, 1)

        self._no_runs_lbl = QLabel("No PSD runs found. Run 'Compute PSDs' first.")
        self._no_runs_lbl.setStyleSheet("color: gray; font-size: 12px;")
        self._no_runs_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_runs_lbl.setVisible(False)
        root.addWidget(self._no_runs_lbl)

    # ------------------------------------------------------------------

    def _refresh(self):
        # Clear existing cards (keep the trailing stretch)
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        runs = psd_params.list_runs(self.project_root)
        if not runs:
            self._no_runs_lbl.setVisible(True)
            self._scroll.setVisible(False)
            return

        self._no_runs_lbl.setVisible(False)
        self._scroll.setVisible(True)

        try:
            manifest = Manifest.load(self.project_root)
        except Exception:
            manifest = None

        for run_name in runs:
            card = self._make_run_card(run_name, manifest)
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)

    def _make_run_card(self, run_name: str, manifest) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(card)
        layout.setSpacing(4)

        # --- Header row ---
        hdr = QHBoxLayout()
        name_lbl = QLabel(run_name)
        name_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        hdr.addWidget(name_lbl)
        hdr.addStretch(1)

        btn_settings = QPushButton("Settings…")
        hdr.addWidget(btn_settings)
        btn = QPushButton("Finalize")
        btn.setStyleSheet("font-weight: bold;")
        hdr.addWidget(btn)
        layout.addLayout(hdr)

        # --- Status rows ---
        psd_dir = self.project_root / "psd" / run_name

        # Pending counts. `pending` is the gate for enabling the Finalize button.
        if manifest is None:
            pending = 0
            pending_text = "—"
            pending_style = "color: gray;"
        else:
            try:
                n_review = len(manifest.pending_psd_review(run_name))
                n_drink = len(manifest.needs_drink_mask(run_name))
                n_verify = len(manifest.pending_drink_verification(run_name))
                pending = n_review + n_drink + n_verify
                if pending == 0:
                    pending_text = "✓ All animals reviewed"
                    pending_style = "color: #1a5c1a;"
                else:
                    parts = []
                    if n_review:
                        parts.append(f"{n_review} pending review")
                    if n_drink:
                        parts.append(f"{n_drink} need drink mask")
                    if n_verify:
                        parts.append(f"{n_verify} pending verification")
                    pending_text = "⚠ " + ", ".join(parts)
                    pending_style = "color: #8a4400;"
            except Exception:
                pending = 0
                pending_text = "Could not read manifest"
                pending_style = "color: gray;"

        status_lbl = QLabel(pending_text)
        status_lbl.setStyleSheet(pending_style)
        layout.addWidget(status_lbl)

        # Source file that will be used
        drink_src = psd_dir / "psds_channel_merged_drink.pkl"
        base_src = psd_dir / "psds_channel_merged.pkl"
        if drink_src.exists():
            src_text = f"Source: {drink_src.name} (drink masks applied)"
            src_style = "color: #1a5c8a;"
        elif base_src.exists():
            src_text = f"Source: {base_src.name}"
            src_style = "color: #333;"
        else:
            src_text = "Source: no merged PKL found yet"
            src_style = "color: gray;"
        src_lbl = QLabel(src_text)
        src_lbl.setStyleSheet(src_style + " font-size: 11px;")
        layout.addWidget(src_lbl)

        # psds_final.pkl status
        final_pkl = psd_dir / "psds_final.pkl"
        if final_pkl.exists():
            ts = datetime.fromtimestamp(final_pkl.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            final_text = f"psds_final.pkl last written {ts}"
            final_style = "color: #333;"
            btn.setText("Re-finalize")
        else:
            final_text = "psds_final.pkl not yet written"
            final_style = "color: gray;"
        final_lbl = QLabel(final_text)
        final_lbl.setStyleSheet(final_style + " font-size: 11px;")
        layout.addWidget(final_lbl)

        # Card background colour
        if pending == 0 and (drink_src.exists() or base_src.exists()):
            card.setStyleSheet(
                "QFrame { background: #f0f7f0; border: 1px solid #c3e6cb; border-radius: 4px; } QLabel { border: none; background: transparent; }"
            )
            btn.setEnabled(True)
            btn.clicked.connect(lambda checked, rn=run_name: self._on_finalize(rn))
        else:
            card.setStyleSheet(
                "QFrame { background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px; } QLabel { border: none; background: transparent; }"
            )
            btn.setEnabled(False)

        # Settings button — enabled whenever params exist
        params = psd_params.load(self.project_root, run_name)
        if params is not None and manifest is not None:
            btn_settings.clicked.connect(
                lambda checked, rn=run_name, rd=psd_dir, p=params, m=manifest: _RunSettingsDialog(
                    self, run_name=rn, run_dir=rd, params=p, manifest=m
                ).exec()
            )
        else:
            btn_settings.setEnabled(False)

        return card

    def _on_finalize(self, run_name: str):
        from ebb.process.psd_compute import build_run_final_pkl

        try:
            out = build_run_final_pkl(self.project_root, run_name)
        except Exception as e:
            QMessageBox.critical(self, "Finalize Failed", str(e))
            return
        QMessageBox.information(
            self,
            "Run Finalized",
            f"psds_final.pkl written for run '{run_name}'.\n\n{out}",
        )
        self._refresh()
