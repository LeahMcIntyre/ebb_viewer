"""Export Masks asks before exporting while SWD review is incomplete."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry


def test_export_stops_when_user_cancels_the_swd_warning(qapp, tmp_path: Path):
    from ebb_viewer.pages.export_masks import ExportMasksPage

    m = Manifest(tmp_path)
    m._entries["A1"] = ManifestEntry("A1", "standard/A1_PREPROCESSED.edf", has_spindle=True,
                                     sleep_qc="ok")
    m.swd_review_enabled = True
    m.save()
    page = ExportMasksPage(project_root=tmp_path)
    with (
        patch.object(page, "_validate_dirname", return_value=(True, "")),
        patch.object(page, "_selected_animals", return_value=["A1"]),
        patch("ebb_viewer.pages.export_masks.confirm_unfinished_swd_review", return_value=False) as c,
        patch("ebb_viewer.pages.export_masks.MaskExportWorker") as worker,
    ):
        page._on_export_clicked()

    assert c.call_args.args[2] == {"A1"}  # checked only the animals being exported
    assert not worker.called
    assert page._worker is None
