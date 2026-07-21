# pre_processing — regenerate the interleaved PDF

These scripts build the shippable **inline** PDF
(`SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline.pdf`) from the **original** book. The
reader (`../reader.py`) does not need them — they only produce the PDF. Run this
if the inline PDF is ever lost.

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

## Regenerate (two steps, from the project root)

```sh
uv run python pre_processing/build_interleaved.py   # 1) draw the pages   (~35 min)
uv run python pre_processing/build_inline.py        # 2) splice + outline (~3 min)
```

That's it — the result is `SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline.pdf`
(≈693 MB, 250,302 pages), self-contained: pages in reading order **and** a
working outline. Ship just that `.pdf`; nothing else is required.

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

### `add_outline.py` (standalone)

Rebuilds the outline on an existing `…_inline.pdf` (~10 s, incremental save).
`build_inline.py` calls it automatically; run it directly only to refresh the
bookmarks without rebuilding the PDF:

```sh
uv run python pre_processing/add_outline.py
```

## Scratch / output files (all in the project root, all gitignored)

| File | From | Keep? |
| --- | --- | --- |
| `…_interleaved.pdf` + `.pages.json` | step 1 | needed by step 2; deletable after |
| `…_inline.pdf` + `.pages.json` | step 2 | **the deliverable** |
| `.enlarged_pages.pdf`, `.qpdf_args.txt` | step 2 scratch | auto-removed |

The inline PDF's `.pages.json` is optional — the app can rebuild its index from
the PDF's own outline (see the main README). `interleave.py` holds the page-layout
logic shared by both build scripts.
