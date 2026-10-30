# ebb-viewer

A desktop app and processing library for rodent EEG/EMG recordings. It takes raw EDF files through sleep scoring
(SleepyRat / SPINDLE), reclassification, quality control and power spectral density (PSD) estimation, and writes the
tables and masks you need for analysis.

## Start here

| If you want to... | Read |
|---|---|
| Understand the pipeline: what each step takes in and puts out, and where files live | [Overview](docs/overview.md) |
| Run the app on a project with the lab defaults | [Quick start](docs/quick_start.md) |
| Install everything on a Windows PC from nothing | [Windows setup](docs/windows_setup.md) |

New here? Do [Windows setup](docs/windows_setup.md) (if you are on Windows), then follow the [Quick start](docs/quick_start.md).
Come back to the [Overview](docs/overview.md) when you want to know what a step does. Unfamiliar terms are in the
[glossary](docs/glossary.md).

## Install and run

```bash
pip install -e .
ebb-viewer
```

Python 3.10 or newer. Step-by-step instructions, including installing Python and Git, are in the
[Windows setup guide](docs/windows_setup.md).

## What the pipeline does

1. **Preprocess** raw EDFs.
2. **Write Spindle EDFs** for the channel combination you chose.
3. **Upload to SleepyRat** and download the scored labels.
4. **Reclassify** NREM gaps and gate on EMG.
5. **Sleep QC**: mark each animal OK, Review or Exclude.
6. **Compute PSDs**, review them, and apply drink masks where needed.
7. **Finalize** and export masks.

Each step has its own page in [docs/steps](docs/steps). The reasoning behind the choices is in the
[decision log](docs/decision_log.md).

## Repository layout

| Folder | Contents |
|---|---|
| `src/ebb/` | Processing library with no GUI: masking, preprocessing, PSD estimation, I/O |
| `src/ebb_viewer/` | Qt GUI that drives the pipeline |
| `analysis/` | Notebooks for sleep-by-hour and PSD analysis |
| `docs/` | User documentation |
| `tests/` | Test suite (`pytest`) |

## Acknowledgements

This project builds on [EBB](https://github.com/mscaudill/ebb) by Matt Caudill. It is largely a refactor with additions:
thresholding features and a GUI.
