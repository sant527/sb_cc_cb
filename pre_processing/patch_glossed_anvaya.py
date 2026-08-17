"""One-off patch: fix the ~331 glossed pages that came out degenerate because the
book printed their word-for-word in anvaya (grammatical) order, which the primary
forward-cursor aligner squashed onto a single Devanagari line.

The alignment fix (draw_glossed -> _gloss_degenerate -> _align_glosses_oi fallback)
only changes those degenerate verses, so instead of rebuilding all 13,000 glossed
pages we redraw just the affected ones and qpdf-splice them in place:
  - a verse the fix now aligns  -> its glossed page is replaced by the redraw
  - a verse still not alignable -> its glossed page becomes a repeat of stretch1

Run once against the current (already-glossed) inline PDF. STRETCH_VERIFY=1 writes
to a temp file for inspection.
"""
import bisect
import os
import subprocess
import sys
import time
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # for `reader`
from interleave import (classify_lines, draw_glossed, _word_for_word, _align_glosses,
                        _gloss_degenerate, WRAP_MAX_FRAC)
from reader import Index, readable

HERE = Path(__file__).resolve().parent.parent
INLINE = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline_interleaved.pdf"
SIDE = INLINE.with_suffix(".pages.json")
CACHE = INLINE.with_suffix(".index.json")
SCRATCH = HERE / ".glossed_patch.pdf"
ARGFILE = HERE / ".qpdf_patch_args.txt"
TMP = HERE / ".inline_patch.tmp.pdf"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def merged_tt(tt, tl):
    if not tl:
        return tt
    full = max(b.width for b in tl)
    out = []
    for t, b in zip(tt, tl):
        if out and b.width < WRAP_MAX_FRAC * full:
            out[-1] += " " + t
        else:
            out.append(t)
    return out


def main():
    t0 = time.time()
    doc = fitz.open(INLINE)
    N = doc.page_count
    idx = Index.load(INLINE, doc)
    sb = [e for e in idx.entries if e.label.startswith("SB ") and e.glossed > 0]

    # find the verses whose OLD alignment was degenerate — those are the only pages
    # the fix touches
    log(f"scanning {len(sb):,} glossed SB verses for degenerate alignment...")
    affected = []
    for e in sb:
        d, tl, tt, _ = classify_lines(doc[e.sloka - 1])
        if not d or not tt:
            continue
        old = _align_glosses(_word_for_word(doc[e.sloka - 1]), merged_tt(tt, tl), len(d), readable)
        if _gloss_degenerate(old):
            affected.append(e)
    log(f"{len(affected):,} degenerate pages to patch")

    # redraw each with the fixed pipeline; True -> corrected gloss (from scratch),
    # False -> not alignable, repeat its stretch1 page
    scratch = fitz.open()
    sub = {}                                     # glossed page (1-based, current) -> (src, srcpage_1based)
    fixed = repeated = 0
    for e in affected:
        p = doc[e.sloka - 1]
        pg = scratch.new_page(-1, width=p.rect.width, height=p.rect.height)
        if draw_glossed(pg, doc, e.sloka - 1):
            sub[e.glossed] = (SCRATCH, scratch.page_count)
            fixed += 1
        else:
            scratch.delete_page(scratch.page_count - 1)
            sub[e.glossed] = (INLINE, e.stretch1)
            repeated += 1
    scratch.save(str(SCRATCH))
    doc.close()
    log(f"redrawn: aligned {fixed:,} | now repeat {repeated:,}")

    # qpdf: emit the whole book, swapping each affected glossed page for its redraw
    toks, prev = [], 0                           # prev = last emitted page (1-based)
    for gp in sorted(sub):
        if gp - 1 >= prev + 1:
            toks += [str(INLINE), f"{prev + 1}-{gp - 1}"]
        src, sp = sub[gp]
        toks += [str(src), str(sp)]
        prev = gp
    if prev < N:
        toks += [str(INLINE), f"{prev + 1}-{N}"]
    ARGFILE.write_text("\n".join(toks) + "\n")

    log("running qpdf splice...")
    ts = time.time()
    subprocess.run(
        ["qpdf", "--warning-exit-0", "--empty", "--pages", f"@{ARGFILE}", "--", str(TMP)],
        check=True)
    log(f"qpdf wrote {TMP.name} in {time.time()-ts:.0f}s")

    # the outline (and page count) are unchanged — pages were swapped 1:1, not
    # inserted — so copy the existing outline over verbatim
    src_doc = fitz.open(INLINE)
    toc = src_doc.get_toc()
    src_doc.close()
    out = fitz.open(TMP)
    assert out.page_count == N, (out.page_count, N)
    out.set_toc(toc)
    out.saveIncr()
    out.close()
    log(f"outline preserved: {len(toc):,} entries")

    if os.environ.get("STRETCH_VERIFY"):
        log(f"STRETCH_VERIFY set — result at {TMP.name}, INLINE untouched")
    else:
        os.replace(TMP, INLINE)
        SIDE.unlink(missing_ok=True); CACHE.unlink(missing_ok=True)
        SCRATCH.unlink(missing_ok=True); ARGFILE.unlink(missing_ok=True)
        log(f"replaced {INLINE.name}: {N:,} pages, {len(sub):,} glossed pages patched")
    log(f"ALL DONE in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
