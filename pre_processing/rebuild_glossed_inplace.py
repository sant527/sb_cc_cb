"""Redraw every glossed page in place with the current draw_glossed.

Unlike patch_glossed_anvaya.py (which touched only the degenerate pages), this
regenerates all ~13,000 glossed pages so every improvement to draw_glossed — the
order-independent fallback, sandhi-elision matching, x-piling detection, and the
grow-page-to-fit-the-translation height fix — reaches every verse consistently.

It's a 1:1 page swap on the already-glossed PDF: each glossed page is replaced by
a fresh draw (or, when the verse still can't be aligned, by a repeat of its
stretched 1/row page). Page count and outline are unchanged. STRETCH_VERIFY=1
writes to a temp file for inspection. Run against the current inline PDF.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # for `reader`
from interleave import draw_glossed
from reader import Index

HERE = Path(__file__).resolve().parent.parent
INLINE = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline_interleaved.pdf"
SIDE = INLINE.with_suffix(".pages.json")
CACHE = INLINE.with_suffix(".index.json")
SCRATCH = HERE / ".glossed_rebuild.pdf"
ARGFILE = HERE / ".qpdf_rebuild_args.txt"
TMP = HERE / ".inline_rebuild.tmp.pdf"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    t0 = time.time()
    doc = fitz.open(INLINE)
    N = doc.page_count
    idx = Index.load(INLINE, doc)
    sb = [e for e in idx.entries if e.label.startswith("SB ") and e.glossed > 0]
    log(f"redrawing {len(sb):,} glossed pages in place...")

    scratch = fitz.open()
    sub = {}                                     # glossed page (1-based) -> (src, srcpage_1based)
    drawn = repeated = 0
    for e in sb:
        p = doc[e.sloka - 1]
        pg = scratch.new_page(-1, width=p.rect.width, height=p.rect.height)
        if draw_glossed(pg, doc, e.sloka - 1):
            sub[e.glossed] = (SCRATCH, scratch.page_count)
            drawn += 1
            if drawn % 2000 == 0:
                log(f"  drew {drawn:,} ({time.time()-t0:.0f}s)")
        else:
            scratch.delete_page(scratch.page_count - 1)
            sub[e.glossed] = (INLINE, e.stretch1)
            repeated += 1
    scratch.save(str(SCRATCH))
    doc.close()
    log(f"redrawn: aligned {drawn:,} | repeat {repeated:,}")

    # qpdf: emit the whole book, swapping each glossed page for its fresh draw
    toks, prev = [], 0
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

    src_doc = fitz.open(INLINE)                   # outline is unchanged (1:1 swap)
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
        log(f"replaced {INLINE.name}: {N:,} pages, {len(sub):,} glossed pages redrawn")
    log(f"ALL DONE in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
