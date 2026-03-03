from pathlib import Path

from PyQt6.QtWidgets import QFileDialog

def pick_edf_csv(parent=None, dir=""):
    """
    Prompts the user to select an EDF file (required) and a CSV file (optional).
    Returns (edf_path, csv_path) or (None, None) if cancelled.
    """
    edf_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Select EDF file",
        dir,
        "EDF files (*.edf);;All files (*)"
    )
    if not edf_path:
        return None, None

    csv_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Select state/labels CSV (optional)",
        dir,
        "CSV files (*.csv);;All files (*)"
    )
    if not csv_path:
        csv_path = None

    return Path(edf_path), (Path(csv_path) if csv_path else None)


def pick_mat(parent=None, dir=""):
    """Prompt the user to select a .mat file.

    Returns the selected Path, or None if cancelled.
    """
    mat_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Select SWD mask .mat file",
        dir,
        "MAT files (*.mat);;All files (*)",
    )
    if not mat_path:
        return None
    return Path(mat_path)

def pick_npy_csv(parent=None, dir=""):
    """ Prompts the user to select a .npy file (required) and a CSV file (optional).
    Returns (npy_path, csv_path) or (None, None) if cancelled.
    """
    npy_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Select Numpy file",
        dir,
        "Numpy files (*.npy);;All files (*)"
    )
    if not npy_path:
        return None, None

    csv_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Select animal video offset CSV (optional)",
        dir,
        "CSV files (*.csv);;All files (*)"
    )
    if not csv_path:
        csv_path = None

    return Path(npy_path), (Path(csv_path) if csv_path else None)