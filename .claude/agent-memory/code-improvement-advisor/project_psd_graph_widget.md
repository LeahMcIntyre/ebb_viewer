---
name: PSDGridPage widget patterns and known issues
description: Recurring patterns, confirmed bugs, and conventions found in psd_graph_widget.py during review
type: project
---

Log-clip bug confirmed: line 395 clips to `y` but `y_copy[m]` is plotted. Fix is `y_copy = np.clip(y_copy, 1e-12, None)`. pyqtgraph does NOT crash on zeros — it converts them to nan gaps via `applyLogMapping`, so the bug causes silent missing data in log-Y mode.

**Why:** The clip output is assigned to a throwaway `y` local, not to `y_copy` which is what `setData` uses.

**How to apply:** When reviewing rendering loops, verify that intermediate transforms (clip, filter, interp) all write back to the variable that is actually passed to `setData`.

Dead code convention: commented-out multi-line string blocks used as comment-out regions (lines 99-103) and stub methods with `print()` (line 535) are project anti-patterns; per project policy they should be deleted.

Double-render on animal navigation: `cmb_animal.currentTextChanged` is connected to both `_render` and `_update_flag_status` separately. This is fine — they are independent updates. Not a double-render of the grid.

Variable shadowing: `act_invfil` is reused for the Interpolate toggle (line 119). Functionally harmless since each action is added to the toolbar before being shadowed, but confusing to read.

QShortcut parenting: shortcuts in `_install_shortcuts` are parented to `self` (the widget) with `WidgetWithChildrenShortcut` context — correct Qt6 pattern, no leak risk.

Magic constant `(0.5, 110)` appears at lines 63 and 338 — should be a single `DEFAULT_XRANGE` class constant.
