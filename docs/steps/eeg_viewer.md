# The EEG viewer

Terms are defined in the [glossary](../glossary.md).

The viewer is not a pipeline step. It is a tool you open from Home or from the command line, to look at one animal's
recording with its sleep states and artifact masks. It never changes data files; the only thing it can write is a Sleep
QC decision in the manifest.

## Purpose

Scroll through a recording, see the sleep state of every epoch, see where each artifact mask falls, and decide whether
the animal is OK or should be excluded. It is where you settle animals marked **Review** in Sleep QC.

## How to open it

| From | How |
|---|---|
| Home | **Open EDF** on an animal's Needs Attention card. The viewer opens with that animal's preprocessed EDF, its state CSV, and the QC buttons. |
| Command line | `ebb-eeg-viewer [folder]` opens a file chooser (an EDF, then an optional state CSV). No QC buttons, because there is no project. |
| Inside the viewer | **File > Open…** (Ctrl+O) opens another recording in a separate window. |

Several viewers can be open at once; each window's title is `EEG Viewer: <animal> (<file>)`.

## Before you run

- A preprocessed EDF (from step 1). The viewer reads any sampling rate, but it **loads the whole recording into memory**
  as 64-bit numbers. A file needing more than about 8 GB is refused with a message to preprocess it first (a raw 5000 Hz,
  48 h, four-channel recording needs about 28 GB; the same recording at 250 Hz needs about 1.4 GB).
- The animal's state CSV, if you want the sleep states and the spindle-noise mask. Opened from Home, the first
  `*labels.csv` for the animal in `spindle_outputs/<COMBO>/` is used. Without a CSV the viewer still works, with no state bar.
- Channel order is fixed: the four channels are shown as LFC, RSC, LSC and EMG, by position.

## Inputs

| Input | Where it comes from | What it is |
|---|---|---|
| Preprocessed EDF | `manifest.json` path, or the file you choose | The traces. |
| State CSV (optional) | `spindle_outputs/<COMBO>/`, or the file you choose | `final_state` if present (shown by default), otherwise the original states. Also `noise_prob` for the spindle-noise mask. |
| SWD file (optional) | **Masks > Load SWD mask (.mat)** | Intervals to shade, as in step 4b. |
| Drink-event file and offsets (optional) | **Masks > Load Drink mask (.npy)** | As in step 8. |
| Annotation file (optional) | **Masks > Load Annotations…** or **Load Annotation Directory…** | Pinnacle events, from the "Time From Start" column. The directory option picks the file for this animal by animal ID. |

## What you see

| Part | Meaning |
|---|---|
| Traces | One per channel, with the animal's recording shown in a window of time. Each channel has its own vertical zoom slider (about 0.01× to 100×) and the label shows the current zoom. |
| State bar | A coloured bar above the traces: Wake amber, NREM blue, REM red, one segment per 4 s epoch, lined up with the traces. The **R** badge beside it is lit when the reclassified states (`final_state`) are shown; click it to see SPINDLE's original states. Display only. |
| Mask shading | Each mask is drawn over the traces in its own colour (see below). |
| Masks panel | A row per mask at the bottom, with a colour swatch, a checkbox to show or hide it, and previous/next arrows to jump to its spans. |
| Time readouts | The position as seconds from the start and as clock time. |
| Status bar | A reminder of the main keys, and a **?** that opens the full list (also F1). |

**Masks that are always built when the file opens**

| Mask | Colour | Meaning |
|---|---|---|
| `commutator` | red | Samples past the amplitude limit, as in step 6 (2000 µV, with the same merge, pad and minimum-event rules). |
| `sd` | orange | Samples past the SD threshold (5 σ, 180 s windows, 0.5 s merge), computed with the commutator-flagged samples left out. |
| `spindle_noise` | green | Epochs whose artifact probability is at or above 0.5. Only if a state CSV is loaded. |

Masks you load add to this list: `swd`, `drink`, `annotation`. Numbers 1 to 9 refer to the masks in this order.

## Controls

**Keyboard** (the trace view must have focus; click on it first)

| Key | What it does |
|---|---|
| `←` / `→` | Scroll half a window. |
| `W` / `N` / `R` | Jump to the next Wake / NREM / REM span. `Shift` + the key jumps to the previous one. |
| `1` to `9` | Jump to the next span of the 1st to 9th mask. `Shift+1` to `Shift+9` jumps to the previous span. |
| `]` / `[` | Next / previous annotation. |
| `Ctrl+S` | Plot the spectrogram (STFT) of the current view. |
| `Ctrl+O` | Open another recording. |
| `Ctrl+Q` | Close the viewer. |
| `F1` | Open the help. |

**Mouse and on-screen controls**

| Control | What it does |
|---|---|
| Double-click a trace | Show that epoch's full row from the state CSV (state, noise probability and the other columns). Needs a CSV. |
| Seconds / view box | How much time is shown at once (0.5 – 1200 s; default 10 s). |
| Jump to (s) | Go to a time in seconds from the start. |
| Scroll slider | Drag through the recording. |
| Per-channel zoom sliders; **Reset Y Zooms** | Zoom each channel vertically; put all back to 1×. |
| Right-click a mask row | **Parameters…** opens its settings (for example the commutator limit or the noise cutoff) and rebuilds the mask. |
| Mask checkbox | Show or hide that mask. |

**Menus**

| Menu | Items |
|---|---|
| File | Open…, Session Information (a text summary of the recording), Quit. |
| Masks | Load SWD mask (.mat), Load Drink mask (.npy), Load Annotations…, Load Annotation Directory…, Mask from Annotations… (enabled once annotations are loaded). |
| Plots | Plot Sleep Data, Plot STFT, STFT Bounds…. |
| Go | Previous / Next Annotation. |
| Help | Keyboard shortcuts and controls (F1). |

**Plots**

- **Plot Sleep Data** opens the same 3 × 3 summary as the Sleep QC Sleep view for this one animal: Wake, NREM and REM in
  columns; fraction of time, number of bouts and mean bout length in rows; one point per 2 h bin, x-axis in hours from the
  start. It uses `final_state` when present. Needs a state CSV.
- **Plot STFT** shows a spectrogram of the current view. **STFT Bounds…** sets the frequency range (default 0 to 120 Hz, or
  the Nyquist rate if lower). The window is 0.5 s.

**Mask parameters, when you right-click**

| Mask | Parameters you can edit |
|---|---|
| `commutator` | `value` (µV), `radius`, `pad`, `min_to_pad` (in samples at the recording's rate) |
| `sd` | `nstd` (σ), `winsize` (s), `radius` (s), `comm_mask` (leave the commutator-flagged samples out) |
| `spindle_noise` | `noise_thresh` (0 – 1) |
| `drink` | `offset` (s), `pad_sec` (s) |
| `annotation` | `keywords`, `match_mode` (contains / exact), `pad_before_sec`, `pad_after_sec` |

Changes here affect only what is drawn. Nothing is saved, and the PSD pipeline does not read them.

## The QC toolbar

Shown only when the viewer was opened from Home (it needs the project's manifest).

| Button | What it does |
|---|---|
| ✓ Mark OK | Set the animal's Sleep QC status to `ok`. |
| Needs Review | Set it to `needs_review`. The animal then shows on Home under Needs Attention. |
| Exclude | Set it to `excluded`. A reason is required (a dialog asks). Pressing it again sends the animal back to `needs_review`. |
| QC: … | The animal's current status. |

Each press is saved to `manifest.json` straight away and confirmed in the status bar. Changing the status to anything other than
`ok` clears the animal's PSD review progress, as in Sleep QC. Details: [step 5](05_sleep_qc.md).

## Fixed values

| Value | Fixed at | Meaning |
|---|---|---|
| Memory limit | 8 GB | Larger recordings are refused. |
| Default masks | commutator, sd, spindle_noise | Built with the values above when the file opens. |
| Epoch | 4 s | State bar and double-click details. |
| Channel labels | LFC, RSC, LSC, EMG | By position. |
| Default view | 10 s | Seconds per view. |
| Viewer masks use the three EEG channels | – | The commutator and SD masks are computed from the three EEG channels on the raw signal, whatever combo the project uses. Step 6 uses the channels you tick, so the two agree when all three are ticked (the default). |

## Outputs

None, except the QC decision written to `manifest.json` (see above). Loaded masks, parameter changes and zoom levels are not
saved.

## If something goes wrong

- "Load Error" with a memory message: the file is too large to hold in memory. Preprocess it first.
- No state bar: no state CSV was found for the animal. Check `spindle_outputs/<COMBO>/` for a `*labels.csv`, or open one by hand with
  File > Open….
- Plot Sleep Data is greyed out: no state CSV loaded.
- "No Annotation File Found": the directory has no file starting with this animal's ID.
- Keys do nothing: click on the traces first so they have focus.

## Known limitations

- **The viewer always uses the three EEG channels** for its commutator and SD masks, whereas step 6 uses the channels you tick, so the masks
  differ if you computed PSDs on fewer channels. On all three channels they match step 6.
