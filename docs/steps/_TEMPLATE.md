# Step page template

Copy this for each step. Fill every section, or write "None" so a reader knows it was not forgotten.
Rules that keep the pages consistent:

- Define a term once, in `glossary.md`, and link to it. Do not re-explain `final_state` or the statuses on every page.
- Use the on-screen label first, then the code or file name in a last column. Outside readers match labels to the methods through that column.
- Every value gets a unit and a default. Every file gets a table of its columns or keys.
- Check every claim against the code before it goes in. Do not leave open markers in a finished page.
- Lab-specific details (who to ask, which software exports a file) go in a box headed **In our lab**, so outside readers can skip them.

---

# Step N. Name

Terms are defined in the [glossary](../glossary.md).

## Purpose
Two sentences: what problem the step solves and what it hands on.

## Before you run
Which earlier steps must be done. Which files you prepare yourself (format, naming, where they go).

## Inputs
| Input | Location | What it is |
|---|---|---|

## Settings
Things **you choose** on the page. If there are none, say so.

| On-screen label | Meaning | Unit | Default | Allowed range | Change it when | Saved as |
|---|---|---|---|---|---|---|

## Fixed values
Values **built into the code** that you cannot change on the page but that shape the result. These are what a methods section must report.

| Value | Fixed at | Meaning | Code name |
|---|---|---|---|

Link the reason to the decision log.

## What it does
Numbered steps, in the order the code runs them.

## Outputs
One table per file: every column, field or key, with its type, allowed values and meaning.
Include what the step records in `manifest.json` and what the page displays.

## Check your work
What a correct run looks like, in concrete terms (counts, ✓ marks, file names).

## If something goes wrong
Symptom → cause → fix.

## Used by
Which later steps read this step's outputs.

## Known limitations
Behaviour that surprises a user and that the page cannot fix: what is not handled, what is not checked, what fails silently. Write "None" if there is nothing.
