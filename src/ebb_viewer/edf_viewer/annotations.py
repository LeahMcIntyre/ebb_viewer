"""Editable span model for Pinnacle-style annotation files.

A loaded annotation file is parsed into mutable :class:`SwdAnnotation`
spans (onset + offset, in seconds from recording start).  The viewer draws
each span as a draggable region; dragging mutates the dataclass in place.
:func:`save_annotation_file` writes the edited spans back to a sidecar file,
preserving the original metadata header and column layout.

Source files carry only a single instant per annotation (``Start Time`` ==
``End Time``), so on load each point is seeded with a small default span
(:data:`DEFAULT_SPAN_SEC`) that the user then drags to mark the true offset.
"""

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

# Width (seconds) seeded for point-in-time annotations so the region has a
# grabbable offset edge. Kept small so new/loaded points read as markers
# rather than auto-expanding to a full span; drag an edge to make them longer.
DEFAULT_SPAN_SEC = 0.1

# Clock formats accepted in the ``Start Time`` / ``End Time`` columns. The
# millisecond form comes first since that is what Pinnacle emits.
_CLOCK_FMTS = ("%m/%d/%y %H:%M:%S.%f", "%m/%d/%y %H:%M:%S")

# Default table columns when starting an annotation set from scratch.
DEFAULT_COLUMNS = [
    "Number",
    "Start Time",
    "End Time",
    "Time From Start",
    "Channel",
    "Annotation",
]


def default_header_lines(
    animal_id: str = "",
    experiment_id: str | None = None,
    researcher: str = "",
) -> list[str]:
    """Return the 6 Pinnacle metadata lines that precede the column header.

    Mirrors the layout Pinnacle emits (and that :func:`save_annotation_file`
    round-trips): six tab-delimited rows of six fields each, the first three
    naming Experiment ID / Animal ID / Researcher, then ``Directory path`` and
    two blank rows. Used to seed an annotation set built from scratch so its
    export matches the original header length and structure.

    ``experiment_id`` defaults to ``animal_id`` since the true experiment ID
    (e.g. a ``_29_91`` session suffix) cannot be derived from the recording.
    """
    exp = experiment_id if experiment_id is not None else animal_id
    return [
        f"Experiment ID\t{exp}\t\t\t\t",
        f"Animal ID\t{animal_id}\t\t\t\t",
        f"Researcher\t{researcher}\t\t\t\t",
        "Directory path\t\t\t\t\t",
        "\t\t\t\t\t",
        "\t\t\t\t\t",
    ]


@dataclass
class SwdAnnotation:
    """A single annotation as an editable onset→offset span."""

    number: int
    label: str
    start_sec: float
    end_sec: float
    channel: str = "ALL"

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)


@dataclass
class AnnotationFile:
    """Parsed annotation file: editable spans plus enough context to round-trip."""

    path: Path
    header_lines: list[str]  # raw lines preceding the table header
    columns: list[str]  # table header field names
    delimiter: str
    start_clock: datetime | None  # absolute recording start (Time From Start == 0)
    annotations: list[SwdAnnotation] = field(default_factory=list)


def _parse_clock(text: str) -> datetime | None:
    text = text.strip()
    for fmt in _CLOCK_FMTS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _fmt_clock(dt: datetime) -> str:
    # Pinnacle uses millisecond precision; strftime's %f gives microseconds.
    return dt.strftime("%m/%d/%y %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def load_annotation_file(path, default_span_sec: float = DEFAULT_SPAN_SEC) -> AnnotationFile:
    """Parse a Pinnacle-style annotation file into editable spans.

    Supports comma- and tab-delimited files. Uses ``Time From Start`` as the
    onset (seconds). Each point annotation is seeded with a ``default_span_sec``
    offset so it presents as a draggable region.
    """
    path = Path(path)
    with path.open("r", newline="") as f:
        raw = f.read()

    delim = "\t" if "\t" in raw.split("\n")[0] else ","
    lines = raw.splitlines()

    table_start = None
    for i, line in enumerate(lines):
        parts = [p.strip() for p in line.split(delim)]
        if "Time From Start" in parts:
            table_start = i
            break

    if table_start is None:
        return AnnotationFile(path, [], [], delim, None, [])

    header_lines = lines[:table_start]
    columns = [c.strip() for c in lines[table_start].split(delim)]

    reader = csv.DictReader(lines[table_start:], delimiter=delim)
    annotations: list[SwdAnnotation] = []
    start_clock: datetime | None = None

    for idx, row in enumerate(reader):
        t_str = (row.get("Time From Start") or "").strip()
        if not t_str:
            continue
        try:
            t_sec = float(t_str)
        except ValueError:
            continue

        start_dt = _parse_clock(row.get("Start Time") or "")
        if start_clock is None and start_dt is not None:
            start_clock = start_dt - timedelta(seconds=t_sec)

        # Honor an existing span (End Time > Start Time) from a previously
        # edited file; only seed the default width for true point annotations.
        end_dt = _parse_clock(row.get("End Time") or "")
        if start_dt is not None and end_dt is not None and end_dt > start_dt:
            end_sec = t_sec + (end_dt - start_dt).total_seconds()
        else:
            end_sec = t_sec + default_span_sec

        num_str = (row.get("Number") or "").strip()
        try:
            number = int(num_str)
        except ValueError:
            number = idx

        annotations.append(
            SwdAnnotation(
                number=number,
                label=(row.get("Annotation") or "").strip(),
                start_sec=t_sec,
                end_sec=end_sec,
                channel=(row.get("Channel") or "ALL").strip(),
            )
        )

    return AnnotationFile(path, header_lines, columns, delim, start_clock, annotations)


def sidecar_path(source: Path) -> Path:
    """Return the default edited-sidecar path for ``source``."""
    source = Path(source)
    return source.with_name(f"{source.stem}_edited{source.suffix}")


def save_annotation_file(annfile: AnnotationFile, out_path) -> Path:
    """Write edited spans to ``out_path``, preserving the original header.

    The table is always written tab-delimited (matching Pinnacle's layout)
    regardless of the source delimiter. Absolute ``Start Time`` / ``End Time``
    clocks are recomputed from ``annfile.start_clock`` (left blank if the
    source had no parseable clock).
    """
    out_path = Path(out_path)
    delim = "\t"
    columns = annfile.columns or list(DEFAULT_COLUMNS)

    with out_path.open("w", newline="") as f:
        for line in annfile.header_lines:
            # Re-delimit the preserved metadata rows so the whole file is tab-
            # delimited even when the source used commas.
            if annfile.delimiter != delim:
                line = line.replace(annfile.delimiter, delim)
            f.write(line + "\n")
        writer = csv.DictWriter(f, fieldnames=columns, delimiter=delim, extrasaction="ignore")
        writer.writeheader()
        for ann in annfile.annotations:
            row = {col: "" for col in columns}
            if "Number" in row:
                row["Number"] = str(ann.number)
            if "Time From Start" in row:
                row["Time From Start"] = repr(ann.start_sec)
            if "Channel" in row:
                row["Channel"] = ann.channel
            if "Annotation" in row:
                row["Annotation"] = ann.label
            if annfile.start_clock is not None:
                if "Start Time" in row:
                    row["Start Time"] = _fmt_clock(
                        annfile.start_clock + timedelta(seconds=ann.start_sec)
                    )
                if "End Time" in row:
                    row["End Time"] = _fmt_clock(
                        annfile.start_clock + timedelta(seconds=ann.end_sec)
                    )
            writer.writerow(row)

    return out_path
