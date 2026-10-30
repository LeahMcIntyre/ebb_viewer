"""PSD Visualizer page — review per-animal PSDs in the review → drink mask → verify loop.

Two review passes, chosen with the buttons at the top (each shows how many animals are
waiting):
- Review PSDs (``psds_<combo>.pkl``): flag each animal OK or needs-drink-mask.
- Verify drink masks (``psds_<combo>_drink.pkl``): check the masks worked.

Other pkls (e.g. psds_drink.pkl, psds_final.pkl) can be opened for ad-hoc viewing under
"Other PSD file" (no flagging).
"""

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ebb.io.psd_store import PSDStore
from ebb_viewer.pipeline import psd_params
from ebb_viewer.pipeline.manifest import (
    DrinkLoopCounts,
    Manifest,
    psd_drink_path,
    psd_path,
)
from ebb_viewer.widgets.collapsible_section import CollapsibleSection
from ebb_viewer.widgets.drink_loop import REVIEW_STEP, VERIFY_STEP, loop_summary_html
from ebb_viewer.widgets.page_help import title_row
from ebb_viewer.widgets.psd_graph_widget import PSDGridPage

_CHANNEL_NAMES = ["LFC", "RSC", "LSC"]

REVIEW = "review"
VERIFY = "verify"


def default_pass(counts: DrinkLoopCounts, has_drink_pkl: bool) -> str:
    """Which pass to open: verification once every PSD has had its first review."""
    if counts.unreviewed == 0 and counts.to_verify > 0 and has_drink_pkl:
        return VERIFY
    return REVIEW


class PSDVisualizer(QWidget):
    """Sidebar page #7 — pick a pass and review animals via PSDGridPage."""

    navigate_to = pyqtSignal(str)
    run_changed = pyqtSignal(str)  # the user picked another PSD run
    manifest_changed = pyqtSignal()  # a review flag changed

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.psd_page: PSDGridPage | None = None
        # Pass the user picked per run; overrides the default until the run changes.
        self._user_pass: dict[str, str] = {}
        # (path, mtime) of the file shown, to re-plot when a rerun rewrites it.
        self._plotted: tuple[str, float] | None = None
        self._build_ui()
        self._wire()
        self._refresh_run_selector()

    def _build_ui(self):
        self.root = QVBoxLayout(self)

        lbl = title_row("PSD Visualizer", "psd_visualizer")
        desc = QLabel(
            "Review each animal's PSD. Mark 'needs mask' if sidebands are visible around "
            "52 and 68 Hz (water bottle artifact), 'ok' otherwise. Animals that need a mask "
            "go to the Drink Mask page and come back here to be verified."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")

        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        desc.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.root.addWidget(lbl)
        self.root.addWidget(desc)

        source_gb = QGroupBox("Source")
        source_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        source_v = QVBoxLayout(source_gb)

        run_form = QFormLayout()
        self.cmb_run = QComboBox()
        self.cmb_run.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cmb_run.setMinimumWidth(160)
        run_form.addRow("Run:", self.cmb_run)
        source_v.addLayout(run_form)

        # Pass switch: the buttons carry the counts of animals waiting in each pass.
        pass_row = QHBoxLayout()
        self.btn_review = QPushButton("Review PSDs")
        self.btn_verify = QPushButton("Verify drink masks")
        self._pass_group = QButtonGroup(self)
        for btn in (self.btn_review, self.btn_verify):
            btn.setCheckable(True)
            btn.setMinimumHeight(30)
            btn.setStyleSheet(
                "QPushButton { font-weight: bold; padding: 2px 14px; }"
                "QPushButton:checked { background: #1a5fa8; color: white; }"
            )
            self._pass_group.addButton(btn)
            pass_row.addWidget(btn)
        self._pass_group.setExclusive(True)
        pass_row.addStretch(1)
        source_v.addLayout(pass_row)

        self._loop_lbl = QLabel("")
        self._loop_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._loop_lbl.setStyleSheet("color: #555; font-size: 11px;")
        source_v.addWidget(self._loop_lbl)

        # Ad-hoc viewing of any other pkl in psd/
        other_body = QWidget()
        other_row = QHBoxLayout(other_body)
        self.cmb_file = QComboBox()
        self.cmb_file.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cmb_file.setMinimumWidth(200)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_browse = QPushButton("Browse…")
        self.btn_plot = QPushButton("Plot PSDs")
        self.btn_plot.setEnabled(False)
        other_row.addWidget(self.cmb_file, 1)
        other_row.addWidget(self.btn_refresh)
        other_row.addWidget(self.btn_browse)
        other_row.addWidget(self.btn_plot)
        source_v.addWidget(CollapsibleSection("Other PSD file", other_body, collapsed=True))
        self.root.addWidget(source_gb, alignment=Qt.AlignmentFlag.AlignTop)

        self._reviewing_lbl = QLabel()
        self._reviewing_lbl.setStyleSheet("font-weight: bold; font-size: 13px; padding: 2px 0;")
        self._reviewing_lbl.setVisible(False)
        self.root.addWidget(self._reviewing_lbl)

        # What to do next in the loop (shown when something is waiting)
        self._next_frame = QFrame()
        self._next_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._next_frame.setStyleSheet(
            "QFrame { background: #fff3cd; border: 1px solid #ffe8a1; border-radius: 4px; }"
        )
        next_layout = QHBoxLayout(self._next_frame)
        next_layout.setContentsMargins(10, 6, 10, 6)
        self._next_lbl = QLabel("")
        self._next_lbl.setWordWrap(True)
        self._next_lbl.setStyleSheet("color: #7a3c00; background: transparent; border: none;")
        next_layout.addWidget(self._next_lbl, 1)
        self._btn_next = QPushButton("")
        self._next_page: str | None = None
        self._btn_next.clicked.connect(lambda: self._next_page and self._go_next(self._next_page))
        next_layout.addWidget(self._btn_next)
        self._next_frame.setVisible(False)
        self.root.addWidget(self._next_frame)

        # Shown when all animals in a run are reviewed
        self._done_hint = QFrame()
        self._done_hint.setFrameShape(QFrame.Shape.StyledPanel)
        self._done_hint.setStyleSheet(
            "QFrame { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; }"
        )
        hint_layout = QHBoxLayout(self._done_hint)
        hint_layout.setContentsMargins(10, 6, 10, 6)
        self._done_hint_lbl = QLabel("✓ All animals in this run reviewed.")
        self._done_hint_lbl.setWordWrap(True)
        hint_layout.addWidget(self._done_hint_lbl, 1)
        self._btn_go_finalize = QPushButton("→ Finalize")
        self._btn_go_finalize.clicked.connect(lambda: self.navigate_to.emit("finalize"))
        hint_layout.addWidget(self._btn_go_finalize)
        self._done_hint.setVisible(False)
        self.root.addWidget(self._done_hint)

        self._is_final_view = False

    def _wire(self):
        self.cmb_run.currentIndexChanged.connect(self._on_run_changed)
        self.btn_refresh.clicked.connect(lambda: self._refresh_run_selector())
        self.btn_browse.clicked.connect(self._on_browse)
        self.btn_plot.clicked.connect(self._on_plot_psds)
        self.cmb_file.currentIndexChanged.connect(self._on_combo_changed)
        self.btn_review.clicked.connect(lambda: self._choose_pass(REVIEW))
        self.btn_verify.clicked.connect(lambda: self._choose_pass(VERIFY))

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_run_selector(auto_plot=True)

    # ----------------------------------------------------------------

    def _current_run_name(self) -> str:
        return self.cmb_run.currentText() or "default"

    def _refresh_run_selector(self, *, auto_plot: bool = False):
        """Repopulate run selector from list_runs(), preserving current selection."""
        current = self.cmb_run.currentText()
        runs = psd_params.list_runs(self.project_root)
        self.cmb_run.blockSignals(True)
        self.cmb_run.clear()
        for r in runs:
            self.cmb_run.addItem(r)
        self.cmb_run.blockSignals(False)
        if current in runs:
            self.cmb_run.setCurrentText(current)
        elif runs:
            self.cmb_run.setCurrentIndex(0)
        self._refresh_pkl_list()
        self._refresh_passes()
        if auto_plot:
            self._auto_plot()

    def _on_run_changed(self):
        self._refresh_pkl_list()
        self._refresh_passes()
        self._auto_plot()
        self.run_changed.emit(self._current_run_name())

    def set_run(self, run_name: str) -> None:
        """Switch to ``run_name`` without plotting (the page plots when it is shown)."""
        if run_name == self.cmb_run.currentText():
            return
        if self.cmb_run.findText(run_name) < 0:
            self._refresh_run_selector()  # a run may have been computed since the list was filled
            if self.cmb_run.findText(run_name) < 0 or run_name == self.cmb_run.currentText():
                return
        self.cmb_run.blockSignals(True)
        self.cmb_run.setCurrentText(run_name)
        self.cmb_run.blockSignals(False)
        self._refresh_pkl_list()
        self._refresh_passes()

    def _refresh_pkl_list(self):
        """Scan psd/<run_name>/ for psds_*.pkl and repopulate the "other file" combo."""
        run_name = self._current_run_name()
        psd_dir = self.project_root / "psd" / run_name
        pkls = sorted(psd_dir.glob("psds_*.pkl")) if psd_dir.is_dir() else []

        current = self.cmb_file.currentData()
        self.cmb_file.blockSignals(True)
        self.cmb_file.clear()
        for p in pkls:
            self.cmb_file.addItem(p.name, str(p))
        self.cmb_file.blockSignals(False)
        if current:
            idx = self.cmb_file.findData(current)
            self.cmb_file.setCurrentIndex(idx if idx >= 0 else 0)
        elif self.cmb_file.count():
            self.cmb_file.setCurrentIndex(0)
        self._on_combo_changed()

    # ---------------- Passes ----------------

    def _pass_paths(self) -> tuple[Path, Path]:
        """(review pkl, verify pkl) of the current run."""
        combo = Manifest.load(self.project_root).combo
        run = self._current_run_name()
        return psd_path(combo, self.project_root, run), psd_drink_path(
            combo, self.project_root, run
        )

    def _refresh_passes(self) -> None:
        """Update the pass buttons, the loop summary and the next-step hint."""
        manifest = Manifest.load(self.project_root)
        run = self._current_run_name()
        counts = manifest.drink_loop_counts(run)
        review_pkl, verify_pkl = self._pass_paths()

        self.btn_review.setText(f"Review PSDs  ({counts.unreviewed} left)")
        self.btn_review.setEnabled(review_pkl.exists())
        self.btn_verify.setText(f"Verify drink masks  ({counts.to_verify} to check)")
        self.btn_verify.setEnabled(verify_pkl.exists())
        self.btn_verify.setToolTip(
            ""
            if verify_pkl.exists()
            else "No drink-masked PSDs yet — flag animals as needing a mask, then apply the "
            "masks on the Drink Mask page."
        )

        self._loop_lbl.setText(
            loop_summary_html(counts, VERIFY_STEP if self.btn_verify.isChecked() else REVIEW_STEP)
        )

        # Next step in the loop
        if counts.unreviewed:
            self._set_next("", None, "")
        elif counts.to_verify:
            self._set_next(
                f"{counts.to_verify} drink-masked PSD{'s' if counts.to_verify != 1 else ''} "
                "to verify.",
                VERIFY,
                "Verify drink masks →",
            )
        elif counts.flagged:
            self._set_next(
                f"{counts.flagged} animal{'s' if counts.flagged != 1 else ''} need a drink mask.",
                "drink_mask",
                "→ 8. Drink Mask",
            )
        else:
            self._set_next("", None, "")

    def _set_next(self, text: str, target: str | None, button: str) -> None:
        self._next_page = target
        self._next_lbl.setText(text)
        self._btn_next.setText(button)
        self._next_frame.setVisible(bool(text))

    def _go_next(self, target: str) -> None:
        """Run the next-step button: switch pass here, or go to another page."""
        if target in (REVIEW, VERIFY):
            self._choose_pass(target)
        else:
            self.navigate_to.emit(target)

    def _wanted_pass(self) -> str:
        """The pass to show: the user's pick for this run, else the default."""
        run = self._current_run_name()
        counts = Manifest.load(self.project_root).drink_loop_counts(run)
        review_pkl, verify_pkl = self._pass_paths()
        picked = self._user_pass.get(run)
        if picked == VERIFY and verify_pkl.exists():
            return VERIFY
        if picked == REVIEW and review_pkl.exists():
            return REVIEW
        return default_pass(counts, verify_pkl.exists())

    def _choose_pass(self, which: str) -> None:
        self._user_pass[self._current_run_name()] = which
        self._auto_plot(force=True)

    def _auto_plot(self, *, force: bool = False) -> None:
        """Show the wanted pass, re-plotting when the file changed (e.g. after a rerun)."""
        which = self._wanted_pass()
        review_pkl, verify_pkl = self._pass_paths()
        target = verify_pkl if which == VERIFY else review_pkl
        (self.btn_verify if which == VERIFY else self.btn_review).setChecked(True)
        if not target.is_file():
            return
        key = (str(target), target.stat().st_mtime)
        if not force and self.psd_page is not None and self._plotted == key:
            return
        self._plot(str(target))

    # ---------------- Other files ----------------

    def _check_done_hint(self):
        self._refresh_passes()
        if not self._is_final_view:
            self._done_hint.setVisible(False)
            return
        try:
            run_name = self._current_run_name()
            counts = Manifest.load(self.project_root).drink_loop_counts(run_name)
            pending = counts.unreviewed + counts.flagged + counts.to_verify
            complete = pending == 0 and self.cmb_file.count() > 0
            self._done_hint.setVisible(complete)
            if complete:
                self._done_hint_lbl.setText(f"✓ All animals in run '{run_name}' reviewed.")
        except Exception:
            self._done_hint.setVisible(False)

    def _on_combo_changed(self):
        path_str = self.cmb_file.currentData()
        self.btn_plot.setEnabled(bool(path_str and Path(path_str).is_file()))

    def _on_browse(self):
        psd_dir = self.project_root / "psd"
        fp = QFileDialog.getOpenFileName(
            self,
            "Select PSD .pkl File",
            str(psd_dir if psd_dir.is_dir() else self.project_root),
            "Pickle Files (*.pkl);;All Files (*)",
        )[0]
        if not fp:
            return
        idx = self.cmb_file.findData(fp)
        if idx < 0:
            self.cmb_file.addItem(Path(fp).name, fp)
            idx = self.cmb_file.count() - 1
        self.cmb_file.setCurrentIndex(idx)

    def _on_plot_psds(self):
        psd_file = self.cmb_file.currentData()
        if psd_file:
            self._plot(psd_file)

    def _plot(self, psd_file: str) -> None:
        if self.psd_page:
            self.psd_page.setParent(None)
            self.psd_page.deleteLater()
            self.psd_page = None

        if not psd_file or not Path(psd_file).is_file():
            return

        stem = Path(psd_file).stem
        combo = Manifest.load(self.project_root).combo
        is_final_view = stem in (f"psds_{combo}", f"psds_{combo}_drink")
        is_drink_review = stem == f"psds_{combo}_drink"
        run_name = self._current_run_name()
        manifest = Manifest.load(self.project_root) if is_final_view else None

        fname = Path(psd_file).name
        if stem == f"psds_{combo}":
            lbl_text = f"Reviewing PSDs — flag each animal ok or needs mask  [run: {run_name}]"
        elif is_drink_review:
            lbl_text = f"Verifying drink masks — check the artifact is gone  [run: {run_name}]"
        else:
            lbl_text = f"Viewing: {fname}  [run: {run_name}]"
        self._reviewing_lbl.setText(lbl_text)
        self._reviewing_lbl.setVisible(True)

        self.psd_store = PSDStore(psd_file, channel_names=_CHANNEL_NAMES)
        self.psd_page = PSDGridPage(
            self,
            store=self.psd_store,
            channel_names=_CHANNEL_NAMES,
            states=None,  # derived from pkl contents (see PSDGridPage)
            manifest=manifest,
            drink_review=is_drink_review,
            run_name=run_name,
            project_root=self.project_root,
        )
        self._is_final_view = is_final_view
        self._plotted = (psd_file, Path(psd_file).stat().st_mtime)
        self._done_hint.setVisible(False)
        self.psd_page.navigate_to.connect(self.navigate_to)
        if is_final_view:
            self.psd_page.manifest_changed.connect(self._check_done_hint)
            self.psd_page.manifest_changed.connect(self.manifest_changed)
            self._check_done_hint()
        else:
            self._refresh_passes()
        self.root.addWidget(self.psd_page)
