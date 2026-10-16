# PSD Methods

How power spectral densities (PSDs) are produced in this pipeline, from raw
EDF to finalized PSD. Written for a methods section / lab reference.
Every value below is read from the code; file references are in
[Source map](#source-map). Remaining caveats are listed under [Open items](#open-items).

## Overview

```
raw EDF ──► PREPROCESS ──► standard/*_PREPROCESSED.edf (250 Hz)
                │
                └─► SPINDLE EDF (channel subset) ──► SPINDLE ──► state CSV (4 s epochs)

standard EDF + state CSV (+ optional SWD / drink / annotation / hour windows)
        │
        ▼
   build masks ──► notch filter ──► masked PSD per state group ──► psds_<COMBO>.pkl
        │
        ▼
   review ──► (drink artifact?) ──► rerun with drink mask ──► finalized PSDs
```

## 1. Preprocessing (`standard/`)

| Step | Value | Notes |
|---|---|---|
| Input sampling rate | 5000 Hz (UI default) | set on the Preprocess page |
| Trim | largest of **48 h / 72 h** that fits in the recording | stop sample rounded up to a whole second; recordings shorter than 48 h raise an error |
| Downsample | factor **20** → **250 Hz** | openseize `resampling.downsample`: polyphase resampling with a Kaiser low-pass anti-alias filter (openseize defaults: cutoff = fs/(2·20) = 125 Hz, passband edge 112.5 Hz, stopband edge 137.5 Hz, ≤0.1 dB passband loss, ≥40 dB stopband attenuation) |
| Output | `<stem>_PREPROCESSED.edf` | 1-second EDF records |

Channels: `LFC, RSC, LSC, EMG`. The PSD step uses channel indices `[0, 1, 2]`
by default (the three EEG channels); the page lets you pick channels.

The SPINDLE upload files (`<stem>_SPINDLE.edf`, in `spindle_edfs/<COMBO>/`)
are a channel subset of the preprocessed EDF; no further signal processing.

## 2. Sleep staging

States come from SPINDLE's output CSV, one row per **4 s epoch**
(`rawstate`/`state` column; `w` = wake, `n` = NREM, `r` = REM). Each epoch
label is repeated `4 s × 250 Hz = 1000` times to give a per-sample mask.

Which animal / channel combo supplies the staging is decided in Sleep QC;
only combos flagged `ok` are merged into the final PSD file (§7).

**State groups** (a separate PSD is produced for each group selected):

| Group | SPINDLE codes |
|---|---|
| wake | w |
| nrem | n |
| rem | r |
| sleep | n + r |
| all | w + n + r |

Default selection: wake, nrem, rem.

Optional confidence filter (`s_prob`): when set, an epoch counts for a state
only if that state's class probability is ≥ `s_prob`. **Off by default.**

## 3. Artifact masks

All masks are boolean at 250 Hz, `True` = keep. They are combined with AND,
then intersected with each state mask. Channels are processed together:
a sample flagged on **any** channel in the combo is masked for all of them.

| Mask | Rule | Default |
|---|---|---|
| **Commutator** | `|x| > 2000 µV` flags a sample. Flagged samples closer than 1 s (250 samples) are merged into one event; events longer than 10 samples are extended by 1 s (250 samples) after their end. | 2000 µV; radius / pad / min length hard-coded |
| **SD threshold** | Signal is cut into **180 s** windows. In each window, z-score every channel using its mean and SD, with commutator-masked samples **excluded from the mean/SD** so they don't inflate it. Samples with `|z| > 5` are flagged; flagged samples within **0.5 s** of each other are merged (gap filled). | 180 s, 5 SD, 0.5 s |
| **SPINDLE noise** | Epochs with SPINDLE noise probability **≥ 0.5** are dropped. | 0.5 |
| **SWD** (optional) | `.mat` file of SWD start/stop times (s) → masked. No padding in the PSD pipeline. | off unless SWD files supplied |
| **Drink** (optional) | 1 Hz `.npy` of drinking events, each dilated **±2 s**, upsampled to 250 Hz, shifted by the per-animal video→EEG offset (CSV `Animal,Offset`). | applied only in the drink-mask rerun (§6) |
| **Annotation** (optional) | Pinnacle annotation events matching user keywords (`contains` match by default), optional padding before/after. | off |
| **Compute hours** (optional) | Keep only samples inside the chosen clock-time windows (decimal hours, windows may wrap midnight), optionally restricted to selected recording days. | off |

### Where SD thresholding applies

The SD threshold is applied **only to wake samples**. For a wake-only group
it is applied to the whole group. For mixed groups (`all`) it is applied to
the wake portion only; NREM/REM samples in that group pass untouched.
NREM-only, REM-only and `sleep` PSDs do **not** use the SD mask. Rationale
in code: SD calibrates to wake amplitudes and would over-mask quieter sleep.

## 4. Filtering

A **60 Hz line-noise notch** is applied to the signal feeding the PSD:

- 8th-order Butterworth **bandstop**, stopband **57–63 Hz**
- zero-phase (forward–backward filtering)
- applied **after** the commutator and SD masks are computed, so artifact
  detection sees unfiltered amplitudes; only the values that enter the PSD
  are filtered

No other filtering (no high-pass, no detrending) is applied by this pipeline.

## 5. PSD estimation

For each (state group ∩ combined artifact mask):

1. Keep only samples where the mask is `True` (masked samples are removed
   from the stream, not zeroed).
2. Estimate the PSD with Welch's method (openseize `spectra.estimators.psd`)
   at fs = 250 Hz, per channel. The app passes no spectral arguments, so
   openseize defaults apply:

   | Setting | Value |
   |---|---|
   | Frequency resolution | 0.5 Hz (segment / FFT length = 250 / 0.5 = 500 samples = 2 s) |
   | Window | Hann |
   | Segment overlap | 50 % |
   | Detrend | constant (subtract segment mean) |
   | Scaling | density (input units² / Hz) |

3. Store `freqs`, `psd`, and `n_estimates` (number of averaged segments).

Groups with no surviving samples (e.g. an animal with no REM) are skipped.

Per result, the fraction of that state's samples removed by each source is
stored: `comm_out_frac`, `sd_out_frac`, `spindle_out_frac`, `swd_out_frac`,
`ann_out_frac`. (`sd_out_frac` is 0 for groups that don't use SD.)
`used_swd / used_drink / used_ann` record whether a source was *configured*,
not whether it removed anything — check the `*_out_frac` for that.

## 6. Review and drink-mask rerun

PSDs are reviewed in the PSD visualizer. An animal showing drinking
artifact is flagged `needs_drink_mask`; the drink mask is then built (§3),
and only those animals are recomputed with identical parameters plus the
drink mask. Rerun outputs go to separate files and never overwrite the
originals (§7).

## 7. Outputs

Under `psd/<run_name>/`:

| File | Contents |
|---|---|
| `psd_params.json` | exact parameters of the run |
| `psds_<COMBO>.pkl` | per-combo PSD records (list of dicts) |
| `psds_channel_merged.pkl` | per animal, the combo flagged `sleep_qc == "ok"`, annotated with `source_combo`. Immutable once built. |
| `psds_drink.pkl`, `psds_channel_merged_drink.pkl` | drink-mask reruns, overlaid on the merged file |
| `psds_final.pkl` | sealed copy of the drink version if present, else the merged one |

## Parameter summary

| Parameter | Value |
|---|---|
| Sampling rate (after preprocessing) | 250 Hz |
| Trim | 48 h or 72 h |
| SPINDLE epoch | 4 s |
| Commutator threshold | 2000 µV (±), 1 s merge, 1 s pad after events >10 samples |
| SD threshold | 5 SD, 180 s windows, 0.5 s merge, wake only |
| SPINDLE noise threshold | 0.5 |
| Drink pad | ±2 s |
| Notch | 60 Hz, 57–63 Hz stopband, 8th-order Butterworth, zero-phase |
| State probability filter | off |
| Welch | 0.5 Hz resolution (2 s), Hann, 50 % overlap, constant detrend, density |

## Open items

- **Per-project values.** Defaults above are the UI defaults and the
  openseize defaults (read from the installed `ebb-dev` environment). Confirm
  against `psd/<run_name>/psd_params.json` for each dataset, since they can
  be changed per run (the KCNT1 script in
  `research/scripts/run_psd_estimation.py` uses `nstd=5` and no SWD/drink
  masks).
- **Segments across masked gaps.** Masked samples are removed and the
  remaining samples are streamed to Welch, so a 2 s segment can span a
  removed gap. Worth stating in methods if reviewers ask.
- **Units.** `psd` is in (signal units)² / Hz; check the EDF's physical
  units (µV expected) before reporting.

## Source map

| Topic | File |
|---|---|
| Preprocess | `src/ebb/preprocess/edf.py`, `src/ebb_viewer/pages/preprocess.py` |
| PSD driver, constants | `src/ebb/process/psd_compute.py` |
| Commutator / SD masks | `src/ebb/masking/threshold.py` |
| State / noise masks | `src/ebb/masking/spindle.py` |
| Drink / SWD / hour windows | `src/ebb/masking/events.py` |
| State groups | `src/ebb/process/state_presets.py` |
| UI defaults | `src/ebb_viewer/widgets/mask_params_widget.py` |
