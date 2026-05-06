from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox


def pick_output_folder(parent, *, suggested: Path) -> Path | None:
    """
    Open a single dialog where the user can navigate anywhere and type a *new* folder name.
    Returns the chosen path (not created yet) or None if cancelled.
    """
    dlg = QFileDialog(parent, "Choose output folder")
    dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)  # acts like "Save As"
    dlg.setFileMode(QFileDialog.FileMode.AnyFile)  # allow typing a new name
    dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)  # dir navigation only
    dlg.setDirectory(str(suggested.parent))
    dlg.selectFile(suggested.name)  # prefill suggested name

    if dlg.exec() != QFileDialog.DialogCode.Accepted:
        return None

    path = Path(dlg.selectedFiles()[0]).expanduser().resolve()
    # Safety prompts
    if path.exists() and any(path.iterdir()):
        btn = QMessageBox.question(
            parent,
            "Folder exists",
            f"“{path}” already exists and isn’t empty.\nUse it anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if btn != QMessageBox.StandardButton.Yes:
            return None
    return path
