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


def pick_annotations_csv(parent=None, dir=""):
    """Prompt the user to select a Pinnacle-style annotation CSV file."""
    path, _ = QFileDialog.getOpenFileName(
        parent,
        "Select annotation CSV",
        dir,
        "CSV files (*.csv *.txt);;All files (*)",
    )
    if not path:
        return None
    return Path(path)


def load_annotations(csv_path) -> list[tuple[float, str]]:
    """Parse a Pinnacle-style annotation CSV and return (t_sec, label) pairs.

    Supports both comma- and tab-delimited files.  Uses the 'Time From Start'
    column for the time value (seconds from recording start).
    """
    import csv as _csv

    csv_path = Path(csv_path)
    with csv_path.open("r", newline="") as f:
        raw = f.read()

    # Auto-detect delimiter
    delim = "\t" if "\t" in raw.split("\n")[0] else ","

    lines = raw.splitlines()

    # Find the header row
    table_start = None
    for i, line in enumerate(lines):
        parts = [p.strip() for p in line.split(delim)]
        if "Time From Start" in parts:
            table_start = i
            break

    if table_start is None:
        return []

    table_str = "\n".join(lines[table_start:])
    reader = _csv.DictReader(table_str.splitlines(), delimiter=delim)

    annotations = []
    for row in reader:
        t_str = (row.get("Time From Start") or "").strip()
        label = (row.get("Annotation") or "").strip()
        if not t_str:
            continue
        try:
            t_sec = float(t_str)
        except ValueError:
            continue
        annotations.append((t_sec, label))

    return annotations