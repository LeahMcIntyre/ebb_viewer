# Cleanup Sweep — Plan & Workflow

This is the durable plan for the project-wide code cleanup sweep. It defines
**what** we're doing, **how** we do it consistently across sessions, and the
**standards** every reviewed file should meet. The live progress checklist
lives in [`REVIEW_PROGRESS.md`](REVIEW_PROGRESS.md).

> **For a future Claude session picking this up cold:** start at
> [§ "Resuming in a new session"](#resuming-in-a-new-session) at the bottom.

---

## Goal

Sweep every source file in `src/` so that the codebase is:
- **Correct** — no off-by-ones, no impossible-case defensive code, no race conditions, edge cases handled at boundaries.
- **Readable** — short methods, clear names, low nesting, no dead code.
- **Documented** — public APIs have docstrings; comments only where the *why* is non-obvious.
- **Simple** — no premature abstractions, no duplication, no compatibility shims for situations that no longer exist.

Test coverage gets extended where it doesn't exist today — primarily for pure-Python helpers extracted from large GUI files.

This is treated as a **focused sprint**, not background work, with the goal of finishing the project cleanly.

---

## Status snapshot at plan-creation time

- Branch `dev`, working tree clean (excluding the new `CLEANUP_PLAN.md` and `REVIEW_PROGRESS.md`).
- `dev` baseline: **257 tests passing** in ~3s.
- `feature/mask_export` is **2 commits ahead of `dev`**, ~2,400 LOC across 10 files. Author intends to merge it before the sweep so cleanup covers it.
- `dev` ↔ `feature/mask_export` merge dry-run: **no conflicts**.
- `stash@{0}` ("On mask_export: HANDOFF.md WIP") is just doc text reflecting the committed Phase 3 state. Apply to `feature/mask_export` before merging.
- Codebase: **60 source files, ~15,000 LOC**. Two outliers at 1,535 lines (`pages/psds.py`, `pages/sleep_qc_visualizer.py`).

---

## Strategy

**Bottom-up, dependency-leaf first.** We start where tests cover us (`ebb/core` → `ebb/io` → `ebb/masking` → ...) and end at the untested giant pages. Reasoning:

- Refactoring a primitive after its callers means redoing the callers. Cleaning it first means each upper-layer pass benefits from the cleaner foundation.
- Bottom layers have tests; top layers don't. Building confidence early reduces risk later.
- Patterns established at the bottom propagate up consistently.

---

## Phase outline

| Phase | Scope | Branch | Sessions (est.) |
|---|---|---|---|
| 0 | Foundation: merge mask_export, adopt ruff, baseline tests, tracker | `cleanup/phase0-foundation` | 1 |
| 1 | `ebb/` library (well-tested, safer) | `cleanup/phase1-ebb` | 3–4 |
| 2 | `ebb_viewer/` infrastructure (`pipeline/`, `widgets/`, `edf_viewer/`, `data_stores/`) | `cleanup/phase2-viewer-infra` | 3 |
| 3 | `pages/` (largely untested, riskiest) | `cleanup/phase3-pages` | 5–6 |
| 4 | Top-level glue (`main_window.py`, `__main__.py`, `__init__.py`s, `_patches.py`) | `cleanup/phase4-toplevel` | ½ |
| 5 | Cross-cutting (consistency, doc consolidation, README, smoke test) | `cleanup/phase5-final` | 1 |

Per-batch file lists, line counts, and per-file checkboxes are in
[`REVIEW_PROGRESS.md`](REVIEW_PROGRESS.md). That file is the live source of
truth for what's done and what's next.

---

## Per-file rubric

Every file gets read against this list. Findings get discussed before edits.

1. **Correctness**
   - Off-by-one in sample-index / mask code (this codebase has lots of `[start:end]` index math).
   - Float `==` comparisons.
   - Edge cases: empty arrays, single-element, NaN, all-masked, zero-length recordings.
   - Mutation of shared state, missing defensive copies of mutable args.
   - Race conditions in `QThread` workers (signals from worker threads, shared state).
   - `fs` hardcoding where a parameter should be threaded through.

2. **Readability**
   - Methods longer than ~40 lines → split.
   - Functions with >5 args → group into a dataclass / config object.
   - Nesting depth >3 → extract or invert.
   - Magic numbers → named constants.
   - Single-letter variables outside very local (≤5 line) scopes.

3. **Documentation**
   - Public class: docstring summarizing role + invariants.
   - Public function: docstring with one-line summary, args, returns, raises.
   - Module: top-of-file docstring summarizing purpose.
   - Inline comments only where the *why* is non-obvious. No comments restating *what* the code does.

4. **Simplification**
   - Dead imports, unused functions, unused class members.
   - Duplicated blocks → helper.
   - Premature abstractions → inline.
   - Defensive checks for situations that can't actually happen in practice.
   - Backwards-compat shims that no caller still needs.

5. **Type hints**
   - All public-API arguments and returns annotated.
   - Internal helpers: hints only where they aid readability.
   - Don't introduce `mypy` as a hard gate yet — that's a separate project.

---

## Per-session loop

Every session follows the same six steps. Don't deviate.

1. **Open `REVIEW_PROGRESS.md`. Pick the next batch.** Smallest unstarted batch in the active phase.
2. **Read each file in the batch fully.** Not skim. The point is to understand.
3. **Run the `code-improvement-advisor` agent on the batch.** Get an external second pass. Bring its findings back into the conversation.
4. **Discuss findings with the user. Decide what to apply.** User has veto on every change.
5. **Apply edits → run pytest → commit per batch (not per file).** Commit message: `Cleanup: <batch name> — <one-line summary>`.
6. **Update `REVIEW_PROGRESS.md`.** Mark items `[x]` (done) / `[~]` (reviewed clean) / `[!]` (changes deferred). Commit the tracker update.

Tests must still pass after every batch. If they don't: fix or revert before the commit.

---

## Branching & commit conventions

- One long-lived `cleanup/<phase>` branch per phase, branched off `dev`.
- Per-batch commits within a phase branch.
- At phase close: tests pass → squash-or-merge `cleanup/<phase>` into `dev`.
- **Never** branch off `main`. Always `dev`. (Project convention.)
- **Never** push `--force` or skip hooks (`--no-verify`).
- Phase 0's ruff steps each get **their own isolated commit** so the diff stays auditable: one commit for the lint auto-fix pass, one for the format pass. No real review changes mixed in.

---

## Tooling

### Conda environment

The user runs all Python commands in the `ebb-dev` conda env. `conda` is not on PATH; use the env's Python directly:

```
/home/matt/miniconda3/envs/ebb-dev/bin/python -m <command>
```

For example:

```
/home/matt/miniconda3/envs/ebb-dev/bin/python -m pytest
/home/matt/miniconda3/envs/ebb-dev/bin/python -m ruff check --fix
/home/matt/miniconda3/envs/ebb-dev/bin/python -m ruff format
```

### Ruff configuration (added in Phase 0)

Add to `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = [
  "E", "W",   # pycodestyle errors/warnings
  "F",        # pyflakes (dead imports, unused vars, undefined names)
  "I",        # isort (import sorting)
  "UP",       # pyupgrade (modern syntax)
  "B",        # bugbear (common pitfalls)
  "SIM",      # simplify (collapse trivially-simplifiable code)
]
ignore = ["E501"]  # line length handled by formatter
```

Why these categories: aggressive enough to clean dead code, imports, and outdated syntax; conservative enough not to drown us in stylistic noise. Expand later if useful.

### Pytest baseline

- Pre-cleanup `dev` baseline: 257 passing.
- After mask_export merge expected: ~317 passing.
- Run from repo root: `…/ebb-dev/bin/python -m pytest`.

---

## Project conventions worth preserving

These are facts about the codebase the sweep should respect (not change):

- `fs = 250` Hz, hardcoded in several places. Don't refactor this away mid-sweep — that's a separate project.
- `ch_names = ("LFC", "RSC", "LSC", "EMG")`.
- EDF stem: `AnimalID_..._PREPROCESSED.edf`. Animal ID = first `_`-delimited token.
- Channel combos like `"LFC_RSC"` are used as both directory names and dict keys.
- Manifest is the authoritative pipeline state store; persists to `project_root/manifest.json` via atomic `.tmp` rename.
- Masks are 1D sample-based spans (not per-channel). Overlay is via semi-transparent `LinearRegionItem` on all channels.
- See `CLAUDE.md` for the rest.

---

## Decisions already made (don't re-litigate)

- **Order:** bottom-up, leaf-first. Not top-down.
- **Linting:** `ruff` with the categories above. Not `mypy` as a hard gate.
- **Branching:** one long-lived `cleanup/<phase>` branch per phase, off `dev`.
- **Pace:** focused sprint to wrap the project, not background-pace.
- **Mask export:** merge `feature/mask_export` into `dev` *before* the sweep starts so cleanup covers it.
- **Tests:** add focused tests for non-trivial pure-Python helpers extracted from untested code (especially in Phase 3), not full GUI coverage.
- **Tracker:** `REVIEW_PROGRESS.md` (markdown checkboxes), not the `TaskCreate` tool — the markdown file persists across sessions.

---

## Open / pending decisions

- **Phase 5 doc consolidation:** `HANDOFF.md`, `PIPELINE_AUDIT.md`, `PLAN.md`, `TODO.md` overlap. Decide at Phase 5 whether to consolidate into one current doc or delete some. Don't decide now.
- **`feature/mask_export` post-merge tweaks:** the user mentioned a couple of changes they want to apply later. Defer to after Phase 1 completes; track in `TODO.md`.
- **Pre-commit hook for ruff:** consider adding after Phase 0 if the auto-fix pass goes well.

---

## Phase 0 — concrete next steps

In execution order:

1. Switch to `feature/mask_export`. `git stash pop stash@{0}`. Verify it touches only `HANDOFF.md`. Commit: "Update HANDOFF.md to reflect committed Phase 3 state".
2. Run pytest on `feature/mask_export` (expect ~317 passing).
3. Switch to `dev`. Create `cleanup/phase0-foundation` branched off `dev`.
4. `git merge --no-ff feature/mask_export -m "Merge feature/mask_export into dev"` (--no-ff keeps the feature branch visible).
5. Pytest post-merge to confirm.
6. Update `REVIEW_PROGRESS.md` to add the new mask_export files into Phase 1d and Phase 3.
7. Add ruff config to `pyproject.toml` (snippet above). Commit: "Phase 0: add ruff config".
8. `ruff check --fix` → review diff → commit: "Phase 0: ruff auto-fix pass".
9. `ruff format` → review diff → commit: "Phase 0: ruff format pass".
10. Pytest. Commit `REVIEW_PROGRESS.md` and `CLEANUP_PLAN.md` (if not already): "Add cleanup sweep plan + tracker".
11. Merge `cleanup/phase0-foundation` → `dev`.

After step 11, the next session opens `REVIEW_PROGRESS.md` and starts Phase 1a (`ebb/core/`).

---

## Resuming in a new session

If you (Claude) are picking this up cold:

1. **Read this file** (`CLEANUP_PLAN.md`) for the workflow and standards.
2. **Read [`REVIEW_PROGRESS.md`](REVIEW_PROGRESS.md)** for the live status. Find the next unchecked batch in the lowest unfinished phase.
3. **Read [`CLAUDE.md`](CLAUDE.md)** for project architecture and conventions.
4. **Check `git status` and `git branch`.** Active branch should be a `cleanup/<phase>` branch. If not, create or switch to one before editing.
5. **Run pytest baseline** before any edits this session: `/home/matt/miniconda3/envs/ebb-dev/bin/python -m pytest --tb=no -q`. Note the count.
6. **Follow the per-session loop above.** Don't skip the `code-improvement-advisor` step — it's the external check.
7. **Don't** start a new phase if the current one is unfinished. Don't reorder phases. Don't skip files.
8. **Update both** the tracker checkboxes and commit them at the end of the session, even if the batch is partial.
