# Pipeline workflow

Three flowcharts of the ebb pipeline, at increasing levels of detail.
Each chart is given in Mermaid (renders in GitHub / IDEs) and as an
ASCII fallback. Step numbers match the sidebar of ebb-viewer; how to run
each step is in [user_guide.md](user_guide.md).

---

## 1. High-level stages

The stages in order. Dashed boxes are optional.

### Mermaid

```mermaid
flowchart TD
    combine["Combine restarted recordings<br/>(command line, optional)"] -.-> pre
    pre["1 Preprocess"] --> spw["2 Spindle EDFs"]
    spw --> up["3 Spindle Upload"]
    up --> rc["4 Reclassify"]
    rc -.-> swd["4b SWD Review<br/>(optional)"]
    rc --> qc["5 Sleep QC"]
    swd -.-> qc
    qc --> psd["6 PSD Computation"]
    psd --> viz["7 PSD Visualizer"]
    viz --> drink["8 Drink Mask"]
    drink --> viz
    viz --> fin["9 Finalize"]
    fin --> ex["10 Export Masks<br/>(optional)"]
    fin --> sleep["Sleep notebooks"]

    classDef optional stroke-dasharray: 4 3;
    class combine,swd,ex optional;
```

### ASCII

```
 - - - - - - - - - - - - - -
 : Combine restarts (CLI)   :
 - - - - - - - - - - - - - -
              v
+------------+   +-----------------+   +------------------+
|1 Preprocess|-->|2 Spindle EDFs   |-->|3 Spindle Upload  |
+------------+   +-----------------+   +---------+--------+
                                                 v
 +----------------+   - - - - - - - - -   +--------------+
 |5 Sleep QC      |<--: 4b SWD Review  :<--|4 Reclassify  |
 +-------+--------+   - - - - - - - - -   +--------------+
         v   (4b is optional; 4 can go straight to 5)
 +---------------+   +----------------+   +--------------+
 |6 PSD Compute  |-->|7 PSD Visualizer|<->|8 Drink Mask  |
 +---------------+   +-------+--------+   +--------------+
                             v
                     +--------------+   - - - - - - - - -
                     |9 Finalize    |-->: 10 Export Masks:
                     +------+-------+   - - - - - - - - -
                            v
                     Sleep notebooks
```

---

## 2. Stages + decision points

Adds the decision gates, and the loops they create.

- **Sleep QC** decides each animal: `ok`, `needs_review` (look again, then `ok` or `excluded`) or `excluded`. An excluded animal is still computed and is marked at Finalize.
- **PSD review** decides each `ok` animal: `ok` or `needs_drink_mask`. A drink-masked animal is recomputed and verified: **Mask worked** gives `ok`, **Redo mask** goes back to `needs_drink_mask`.
- **Finalize** waits until no animal is unreviewed, flagged, or waiting for verification.

### Mermaid

```mermaid
flowchart TD
    pre["1 Preprocess"] --> spw["2 Spindle EDFs"]
    spw --> up["3 Spindle Upload"]
    up --> rc["4 Reclassify"]
    rc --> swdq{"SWD review<br/>enabled?"}
    swdq -- yes --> swd["4b SWD Review"]
    swdq -- no --> qc
    swd --> qc["5 Sleep QC"]

    qc --> qcg{"Sleep QC decision"}
    qcg -- needs_review --> rev["Review in EDF viewer"]
    rev --> qcg
    qcg -- excluded --> psd
    qcg -- ok --> psd["6 PSD Computation"]

    psd --> viz["7 PSD Visualizer"]
    viz --> pg{"PSD review"}
    pg -- ok --> fin
    pg -- needs_drink_mask --> drink["8 Drink Mask"]
    drink --> ver["Verify in PSD Visualizer"]
    ver --> vg{"Mask worked?"}
    vg -- yes --> fin
    vg -- no --> drink

    fin["9 Finalize"] --> done(["psds_final.pkl"])

    classDef gate fill:#fec,stroke:#a73,color:#311;
    class swdq,qcg,pg,vg gate;
```

### ASCII

```
 1 Preprocess -> 2 Spindle EDFs -> 3 Spindle Upload -> 4 Reclassify
                                                            |
                                  SWD review enabled?  yes  |  no
                                         +------------------+--------+
                                         v                           |
                                 4b SWD Review                       |
                                         |                           |
                                         v                           v
                                       +---------------------------------+
                                       |          5 Sleep QC             |<--+
                                       +----------------+----------------+   |
                                                        v                    |
                                                 /-------------\             |
                                                < QC decision?  >-------------+
                                                 \------+------/  needs_review
                                              ok /      | excluded  (review EDF,
                                                 +------+           then ok/excluded)
                                                        v
                                               6 PSD Computation
                                                        v
                                               7 PSD Visualizer
                                                        v
                                                 /-------------\
                                                <  PSD review?  >--- needs_drink_mask
                                                 \------+------/            |
                                                   ok   |                    v
                                                        |           8 Drink Mask (rerun)
                                                        |                    v
                                                        |            Verify: mask worked?
                                                        |             yes |       | no
                                                        |<----------------+       +--> back to 8
                                                        v
                                                  9 Finalize
                                                        v
                                                 psds_final.pkl
```

---

## 3. Stages + inputs/outputs (full picture)

The folders and files each step reads and writes, under the project folder.
Cylinders are folders or files on disk.

### Mermaid

```mermaid
flowchart TD
    raw[("Raw EDFs<br/>(project folder)")] --> pre["1 Preprocess"]
    restarts[("Restart chunks<br/>EDF, SWD, annotations")] -.-> comb["ebb-combine"]
    comb -.-> raw
    comb -.-> short[("short_files/<br/>original chunks")]

    pre --> std[("standard/")]
    std --> spw["2 Spindle EDFs"]
    spw --> sedf[("spindle_edfs/COMBO/")]
    spw --> man[("manifest.json<br/>(combo, statuses, notes)")]

    sedf --> up["3 Spindle Upload"]
    up --> sout[("spindle_outputs/COMBO/<br/>labels CSVs")]

    sout --> rc["4 Reclassify"]
    std --> rc
    rc --> sout2[("CSVs + reclass_state<br/>+ final_state<br/>(_original/ keeps SPINDLE's file)")]

    swdmat[("swd/ .mat files")] -.-> swd["4b SWD Review"]
    sout2 -.-> swd
    swd -.-> sout2

    sout2 --> qc["5 Sleep QC"]
    qc --> man

    std --> psd["6 PSD Computation"]
    sout2 --> psd
    swdmat -.-> psd
    ann[("annotations folder<br/>(chosen on the page)")] -.-> psd
    man --> psd
    psd --> pkl[("psd/RUN/<br/>psd_params.json<br/>psds_COMBO.pkl")]

    pkl --> viz["7 PSD Visualizer"]
    viz --> man
    viz --> drink["8 Drink Mask"]
    dm[("drink_masks/<br/>ID.npy + offsets CSV")] --> drink
    drink --> dpkl[("psds_drink.pkl<br/>psds_COMBO_drink.pkl")]
    dpkl --> viz

    pkl --> fin["9 Finalize"]
    dpkl --> fin
    man --> fin
    fin --> final[("psds_final.pkl<br/>excluded_animals.csv")]
    final --> xlsx[("Excel export")]

    sout2 --> exm["10 Export Masks"]
    std --> exm
    exm --> exp[("exports/NAME/<br/>states, artifacts,<br/>clean_per_state CSVs")]

    sout2 --> nb["Sleep notebooks"]
    nb --> sa[("sleep_analysis/")]

    classDef artifact fill:#eef,stroke:#557,color:#113;
    class raw,restarts,short,std,sedf,man,sout,sout2,swdmat,ann,pkl,dm,dpkl,final,xlsx,exp,sa artifact;
```

### Folder layout (ASCII)

```
project/
  *.edf                       raw recordings (one per animal)
  short_files/                original restart chunks, after ebb-combine
  standard/                   1 Preprocess
  spindle_edfs/COMBO/         2 Spindle EDFs
  spindle_outputs/COMBO/      3 Spindle Upload; 4 Reclassify adds columns
    _original/                SPINDLE's untouched CSVs
  swd/                        SWD .mat files (one per animal)
  drink_masks/                ID.npy per animal + one offsets CSV
  psd/RUN/                    6-9: psd_params.json, psds_COMBO.pkl,
                              psds_drink.pkl, psds_COMBO_drink.pkl,
                              psds_final.pkl, excluded_animals.csv
  exports/NAME/               10 Export Masks
  sleep_analysis/             sleep notebooks
  manifest.json               project combo and per-animal statuses
```

---

## Notes

- `COMBO` is the project's channel combo (for example `LFC_RSC`), set when the SPINDLE EDFs are written. A project has exactly one combo; there is no per-animal combo and no Rerun page.
- Sleep QC statuses: `None | "ok" | "needs_review" | "excluded"`. PSD statuses: `None | "ok" | "needs_drink_mask" | "drink_mask_applied"`. An exclusion needs a written reason.
- Everything downstream of Reclassify reads `final_state`, not SPINDLE's original states.
- `Manifest.build_from_standard()` syncs new files from disk without overwriting existing flags, so rerunning an earlier step does not clear later decisions.
- The annotation folder is chosen on the PSD Computation page and is not required to live in the project folder.
