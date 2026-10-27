# Documentation plan

Three documents, written in this order. Each feeds the next.

| # | Document | Audience | Answers | Lives at |
|---|---|---|---|---|
| 1 | **User guide** | A lab member who has never seen the tool | "How do I run my data through this?" | `docs/user_guide.md` |
| 2 | **Decision log** | Future you, collaborators, reviewers | "Why does it work this way, and what did I weigh?" | `docs/decision_log.md` |
| 3 | **Methods draft** | Paper readers | "What exactly was done to the data?" | `docs/methods_draft.md` (later) |

The user guide says *what to do*; the decision log says *why*; the methods
draft is the decision log with the narrative stripped out and only the
reportable facts kept. So the log should record parameters and rationale at
the level of detail the paper will need.

## What already exists (reuse, don't rewrite)

| Existing file | Use it for |
|---|---|
| `docs/windows_setup.md` | User guide, Install section. Link or fold in. |
| `docs/pipeline_flow.md` | User guide overview figure. **Stale**: still shows `needs_rerun`, the Rerun page, and multi-combo. Redraw to match the current stages (Reclassify, SWD Review, Finalize, Export Masks). |
| `docs/sleep_reclassification.md` | Decision log (reclassification, SWD) and user guide pages 4/4b. |
| `docs/sleep_qc_and_exclusion.md` | Decision log (exclusion policy) and user guide pages 5-7, 9. |
| `docs/psd_methods.md` | Closest thing to methods text today. Seed for document 3. Its values are read from the code, so keep it as the parameter reference. |
| `PITFALLS.md` | Developer-facing. Mine for decisions whose "why" is already written down. |
| `TODO.md` | Open scientific questions (SWD masks and TS policy, REM-in-multiple-groups, lumped-state SD threshold). These belong in the log as "Open questions". |
| `analysis/sleep_by_hour*.ipynb` | User guide, Sleep analysis section. |
| `README.txt` | Needs the acknowledgements/credit fixed before anything is public. |

## Steps

1. **Fix the stale pieces first.** Redraw `pipeline_flow.md`. Decide the doc
   file layout (this plan assumes `docs/`). Small, and everything else links
   to it.
2. **Write the user guide skeleton**, then fill it by walking the app with
   a real (or demo) project, page by page. Screenshots come from that pass.
   Fill order: Install, Quick start, then one section per page in pipeline order.
3. **Write the decision log as you go, not at the end.** Make one dated
   entry per decision while it is fresh. For past decisions, do a
   one-sitting interview pass (see below) and capture the answers verbatim
   before polishing.
4. **Cross-check.** Every parameter in the user guide should appear in the
   log with a reason. Anything in the log with no home in the guide is
   either an internal detail or a missing guide section.
5. **Then the methods draft**, built from the log's "Parameters" tables and
   `psd_methods.md`.

### Getting the decision log out of your head

The log is the hard one because the reasoning is in your memory, not the
code. Suggested process: pick one stage per sitting, and for each choice
fill in the entry template below. If you want, I can interview you stage by
stage (asking the questions in the template) and draft the entries from
your answers. The code and git history can supply the *what* and *when*;
only you can supply the *why*.

Entry template (copy for each decision):

```
### <Decision, stated as a choice>
- Stage:            (which pipeline step)
- Chosen:           (the value / approach, with units)
- Alternatives:     (what else you considered)
- Why:              (data you looked at, literature, lab convention, constraint)
- Evidence:         (notebook / figure / commit / paper)
- Confidence:       (settled | provisional | needs discussion)
- Affects results?  (yes -> must go in the paper's methods)
- Where in code:    (file, parameter)
- Revisit if:       (what would change your mind)
```

---

# Outline 1: User guide (`docs/user_guide.md`)

Task-oriented. Each page section follows the same four-part shape:
**Goal, Before you start, Steps, Check your work** (plus "If something
goes wrong").

## 0. Front matter
- What ebb does, in one paragraph and one diagram (the redrawn pipeline flow)
- What you need: recordings (EDF format, 5 kHz, channels LFC/RSC/LSC/EMG),
  SleepyRat/SPINDLE account, disk space estimate
- Credit to the original EBB library (Caudill) and what is new here

## 1. Installation and first launch
- Windows (link to or merge `windows_setup.md`), macOS/Linux
- `pip install -e .`, `ebb-viewer`
- Updating; verifying the install; troubleshooting

## 2. Concepts you need before the first click
- The project folder: what goes where (`standard/`, `spindle_edfs/`,
  `spindle_outputs/`, `psd/`, `manifest.json`); a folder tree figure
- The manifest: per-animal status, why you should not hand-edit it
- The channel combo (one per project)
- Sleep states (w / n / r), 4 s epochs
- Original vs. reclassified states (`final_state`): the one thing all
  analysis reads
- Statuses cheat sheet: `ok`, `needs_review`, `excluded`;
  `needs_drink_mask`, `drink_mask_applied`

## 3. Quick start: one project end to end
- Condensed checklist of all stages with expected time per stage
- Minimal run on a small demo set (needs a demo dataset: **to create**)

## 4. Page-by-page reference (pipeline order)
One section each, same four-part shape:
- Home / project picker (build-from-standard sync, pipeline summary table)
- 1. Preprocess
- 2. Spindle Write
- 3. Spindle Upload / Download (credentials, skipping files already
  uploaded, downloading label CSVs)
- 4. Reclassify (NREM gap fill, EMG gate, what the gate decision means)
- 4b. SWD Review (optional, how to opt in)
- 5. Sleep QC (Overview boxplots and thresholds; by-hour grid; OK / Review /
  Exclude; reason required; Show original)
- 6. PSD Compute
- 7. PSD Visualizer (flag drink artifacts; exclude from here)
- 8. Drink Mask
- 9. Finalize (what gets sealed; what "excluded" looks like in outputs)
- 10. Export Masks
- The EDF viewer: keyboard shortcuts (`w` / `n` / `r` jumps), masks dock

## 5. Sleep analysis (outside the GUI)
- Which notebook to use: `sleep_by_hour.ipynb` (quick) vs.
  `sleep_by_hour_walkthrough.ipynb` (explained)
- Settings to change; what the output files are; how excluded animals are
  handled

## 6. Common workflows
- Add animals to an existing project
- Re-run one animal
- Exclude an animal, and un-exclude it
- Redo PSDs with different parameters
- Hand off a finished project to someone else

## 7. Troubleshooting
- By symptom: "page is greyed out", "upload skipped everything",
  `NotReclassifiedError`, mismatched sampling rate, empty PSD file
- Where logs and errors appear

## 8. Reference
- Output file formats (`psds_final.pkl`, `excluded_animals.csv`, state CSV
  columns)
- Glossary
- Parameter defaults (table, linked to the decision log)

## Prerequisites to write this guide
- A demo dataset and a clean-run walkthrough with screenshots
- Decide whether SleepyRat credential setup is documented (see the TODO about
  credentials in source)

---

# Outline 2: Decision log (`docs/decision_log.md`)

Organized by **pipeline stage**, so it lines up with the guide and the
eventual methods section. Each stage section opens with a one-paragraph
summary, a **Parameters table** (value / units / why / confidence), then
the individual decision entries (template above), then **Open questions**.

## 0. Preface
- Purpose and how to read it; confidence labels; date convention
- Scientific context: the question, the species and recordings, what the
  pipeline's outputs are used for
- Design principles you applied across stages (e.g. one project = one
  channel combo; analysis only reads reclassified states; excluded animals
  stay in the data and are marked rather than deleted; no legacy
  compatibility code)

## 1. Data acquisition and preprocessing
- Recording duration: 48 h / 72 h trim rule
- Why 5 kHz in, 250 Hz out; downsampling filter choice
- Channel set and ordering; why the EMG is kept
- File naming and animal ID convention

## 2. Sleep staging with SPINDLE
- Why SPINDLE (vs. manual scoring or other classifiers)
- Epoch length (4 s) and state codes
- Which channel combination, and how it is chosen (one combo per project,
  why not per-animal)
- Remote upload workflow tradeoffs

## 3. State reclassification
- Why reclassify SPINDLE output at all (the motivating failure cases)
- NREM gap-fill rule: parameters and how tuned
- EMG gate: threshold choice, per-animal vs. global, what it fixes
- Keeping original states alongside `final_state`

## 4. SWD review
- Why SWDs matter in this model; why the review is optional and opt-in
- What reviewers can change; what counts as reviewed vs. waived
- Policy on SWD epochs in downstream analysis (open question in TODO)

## 5. Quality control and exclusion
- Metrics used for flagging; threshold values and where they came from
- Why boxplot overview first, then by-hour grid
- Exclusion criteria, the required-reason rule, and why excluded animals are
  retained and marked instead of dropped
- Known gaps (e.g. exports include excluded animals unmarked)

## 6. PSD estimation
- Method (Welch / STFT / whichever is used), window, overlap, frequency
  resolution, and why
- State groups and defaults; lumped groups and the SD-threshold rule;
  REM-in-multiple-groups semantics
- Notch filtering
- Artifact masking: SD thresholds, commutator mask, why these values
- Hour windows and how they interact with masks

## 7. Drink-mask artifacts
- What the artifact looks like and why it needs its own mask
- Detection by eye (PSD review) vs. automatic; why manual
- How the rerun is scoped (subset reruns, offsets CSV)

## 8. Finalization and export
- What "sealed" means and why PSD files are immutable
- Merging channels; snapshot of exclusions
- Mask export format and intended consumers

## 9. Sleep-by-hour analysis
- Why a transparent notebook instead of a GUI page
- Hour binning, handling of recording start times, per-day vs. from-start
- What is computed from `final_state` and what is left out

## 10. Software and architecture choices
- Why a pure-processing library plus a separate Qt GUI
- Manifest as single source of truth; atomic writes
- Relationship to upstream EBB: what was kept, what was rewritten
- Testing approach and its gaps

## 11. Things that went wrong (lessons)
- Curated from `PITFALLS.md`, framed scientifically where relevant
  (e.g. analysis falling back to original states would silently change results)

## 12. Open questions and deferred decisions
- Consolidated from `TODO.md` and per-stage lists; each with what is needed
  to settle it

## 13. Appendix
- Full parameter table (all stages) feeding the methods draft
- Bibliography of papers and tools that informed decisions
- Changelog of decisions that were later reversed

---

## Suggested next step

Start with the decision log's **Parameters table for stage 6 (PSD
estimation)**: `psd_methods.md` already has the values, so you only need
to add the "why" column, and it is the part of the methods most likely to
be scrutinized.
