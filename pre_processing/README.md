# pre_processing — regenerate the interleaved PDF

These scripts build the shippable **inline** PDF
(`SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline_interleaved.pdf`) from the **original** book. The
reader (`../reader.py`) does not need them — they only produce the PDF. Run this
if the inline PDF is ever lost.

> **Shortcut:** the finished PDF is also on Google Drive, so you can just download
> it instead of rebuilding:
> <https://drive.google.com/file/d/1k3LtAIs6cjga4e4uxo07PJLQmUgX9q8l/view?usp=drive_link>

Everything runs from the **project root** (the parent of this folder), and every
file lives there — the scripts just live in `pre_processing/`.

## Prerequisites

1. **The original PDF** in the project root, named exactly
   `SB_CC_CB_ALL_NEW_INDEX_Oct3_2021.pdf` (~538 MB). Download it from:

   <https://drive.google.com/file/d/186cFWCiBbdWzaIP6EMdEyM1cqCSW-qX5/view?usp=drive_link>

2. **qpdf** — used to splice pages by reference (fast). PyMuPDF/pikepdf can't do
   it at this scale (O(n²), hours).

   ```sh
   brew install qpdf        # macOS
   sudo apt install qpdf    # Debian/Ubuntu
   ```

3. Python deps are in `pyproject.toml` — `uv run` installs them automatically.

## Regenerate (four steps, from the project root)

```sh
uv run python pre_processing/build_interleaved.py   # 1) draw the pages       (~35 min)
uv run python pre_processing/build_inline.py        # 2) splice + outline     (~3 min)
uv run python pre_processing/add_clubbed.py         # 3) add clubbed pages    (~10 min)
uv run python pre_processing/add_stretched.py       # 4) add stretched pages  (~25 min)
uv run python pre_processing/add_stretched_notl.py  # 5) add no-roman pages   (~25 min)
```

That's it — the result is `SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline_interleaved.pdf`,
self-contained: pages in reading order **and** a working outline. Ship just that
`.pdf`; nothing else is required.

### What each step does

1. **`build_interleaved.py`** — the slow, expensive part. For every transformable
   SB verse it *draws* an interleaved page (transliteration paired with enlarged
   Devanagari) and appends it at the **tail** of a copy of the original, writing
   `…_interleaved.pdf` + a `.pages.json` sidecar. Tail placement + incremental
   save keep this as fast as drawing allows, but the pages aren't in reading
   order yet.

2. **`build_inline.py`** — the cheap part. It **reuses** those already-drawn
   interleaved pages (no redraw), *draws* only the few hundred enlarged-sloka
   fallbacks, and uses **qpdf** to splice each verse's enhanced page physically
   right after its sloka, in reading order. It then calls `add_outline.py` to
   rebuild the bookmarks (which qpdf drops) with corrected page numbers plus a
   `» interleaved` jump under each verse.

   `build_inline.py` **needs `…_interleaved.pdf`** from step 1 — don't delete it
   until the inline build finishes.

3. **`add_clubbed.py`** — runs on the finished inline PDF. For each of the ~6,980
   one-pada/line verses it *draws* a **clubbed** page (two padas side by side)
   and qpdf-splices it right after the sloka, before the enlarged page, so the
   order becomes `sloka → clubbed → large`. It rebuilds the outline with a
   `» clubbed` + `»» read large` child per clubbed verse and removes the stale
   sidecar. Idempotent: it refuses to run if the outline already has clubbed
   entries. See the main README's *pada packing* section for the split.

4. **`add_stretched.py`** — runs on the inline PDF. For every SB verse with
   Devanagari it *draws* two **stretched** reading pages (`interleave.draw_stretched`)
   — one pada per row and two padas per row — with the Devanagari scaled by a
   single factor to fill the page width and trailing dandas / verse numbers
   stripped. qpdf splices both in after the verse's existing enhanced page(s):
   `sloka → [clubbed] → large → stretched(1/row) → stretched(2/row)`. The outline
   gets two `▸ stretched` children per verse (the reader exposes them as the
   *Stretch 1/row* and *Stretch 2/row* nav modes). Idempotent. `STRETCH_VERIFY=1`
   writes to a temp file for inspection instead of replacing the PDF.

5. **`add_stretched_notl.py`** — same stretched pages but with the roman sloka
   dropped (`draw_stretched(…, translit=False)`): just the full-width Devanagari,
   word-for-word, and translation. Two per verse (1/row, 2/row), spliced after the
   verse's `▸ stretched (2/row)` page, adding two `▸ stretched no-roman` children
   (reader modes *Stretch 1/row (no roman)* and *Stretch 2/row (no roman)*). Run
   after step 4. Idempotent; `STRETCH_VERIFY=1` supported.

### `add_outline.py` (standalone)

Rebuilds the outline on an existing `…_inline_interleaved.pdf` (~10 s, incremental save).
`build_inline.py` calls it automatically; run it directly only to refresh the
bookmarks without rebuilding the PDF:

```sh
uv run python pre_processing/add_outline.py
```

## Scratch / output files (all in the project root, all gitignored)

| File | From | Keep? |
| --- | --- | --- |
| `…_interleaved.pdf` + `.pages.json` | step 1 | needed by step 2; deletable after |
| `…_inline_interleaved.pdf` + `.pages.json` | step 2 | **the deliverable** |
| `.enlarged_pages.pdf`, `.qpdf_args.txt` | step 2 scratch | auto-removed |

The inline PDF's `.pages.json` is optional — the app can rebuild its index from
the PDF's own outline (see the main README). `interleave.py` holds the page-layout
logic shared by both build scripts.
