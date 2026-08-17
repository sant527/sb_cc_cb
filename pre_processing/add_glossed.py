"""Add a glossed reading page to every SB verse.

For each one-pada/line verse (~6,985), draw a glossed page — the full-width
Devanagari with the printed word-for-word placed above each word (transliteration
grey, meaning + underline alternating purple/teal) and only the translation
below. Verses whose Devanagari can't be line-paired (the two-padas/line ones)
can't be aligned, so their glossed slot is a **repeat of their stretched 1/row
page** — that keeps every verse with a glossed page so the nav mode is uniform.

The page is qpdf-spliced after the verse's last stretched page (stretch4). The
outline gets a `▸ glossed` child; the reader exposes it as nav mode 7 and renders
these pages with saturation preserved so the purple/teal stay true in any theme.
Run after add_stretched_notl.py. Idempotent; STRETCH_VERIFY=1 for a temp file.
"""
import bisect
import os
import subprocess
import sys
import time
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # for `reader`
from interleave import classify_lines, draw_glossed, _word_for_word
from reader import Index

HERE = Path(__file__).resolve().parent.parent
INLINE = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline_interleaved.pdf"
SIDE = INLINE.with_suffix(".pages.json")
CACHE = INLINE.with_suffix(".index.json")
SCRATCH = HERE / ".glossed_pages.pdf"
ARGFILE = HERE / ".qpdf_glossed_args.txt"
TMP = HERE / ".inline_glossed.tmp.pdf"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    t0 = time.time()
    doc = fitz.open(INLINE)
    N = doc.page_count
    old_toc = doc.get_toc()
    if any("▸ glossed" in t for _, t, _ in old_toc):
        log("outline already has '▸ glossed' entries — nothing to do."); return
    idx = Index.load(INLINE, doc)
    sb = [e for e in idx.entries if e.label.startswith("SB ") and e.stretch4 > 0]

    log(f"drawing glossed pages for {len(sb):,} SB verses...")
    scratch = fitz.open()
    jobs = []                          # (insert_after_0based, from_scratch, page_1based, label)
    drawn = repeated = 0
    for e in sb:
        s0 = e.sloka - 1
        p = doc[s0]
        pg = scratch.new_page(-1, width=p.rect.width, height=p.rect.height)
        if draw_glossed(pg, doc, s0):                                      # real glossed page
            jobs.append((e.stretch4 - 1, True, scratch.page_count, e.label))
            drawn += 1
            if drawn % 2000 == 0:
                log(f"  drew {drawn:,} ({time.time()-t0:.0f}s)")
        else:                                                              # repeat stretched 1/row
            scratch.delete_page(scratch.page_count - 1)
            jobs.append((e.stretch4 - 1, False, e.stretch1, e.label))
            repeated += 1
    scratch.save(str(SCRATCH))
    doc.close()
    jobs.sort()
    inserts = [q for q, _, _, _ in jobs]
    log(f"glossed: drawn {drawn:,}  |  repeated (non-alignable) {repeated:,}  |  total {len(jobs):,}")

    # qpdf job: one page after each verse's stretch4 — from the scratch (drawn) or
    # from the inline itself (a repeat of its stretched 1/row page)
    toks, prev = [], 0
    for q, from_scratch, pg, _ in jobs:
        toks += [str(INLINE), f"{prev + 1}-{q + 1}"]
        toks += [str(SCRATCH) if from_scratch else str(INLINE), str(pg)]
        prev = q + 1
    toks += [str(INLINE), f"{prev + 1}-{N}"]
    ARGFILE.write_text("\n".join(toks) + "\n")
    log("running qpdf splice...")
    ts = time.time()
    subprocess.run(
        ["qpdf", "--warning-exit-0", "--empty", "--pages", f"@{ARGFILE}", "--", str(TMP)],
        check=True)
    log(f"qpdf wrote {TMP.name} in {time.time()-ts:.0f}s")

    def new0(p):
        return p + bisect.bisect_left(inserts, p)

    glossed_pg = {lab: new0(q) + 2 for q, _, _, lab in jobs}   # label -> new glossed page

    new_toc, pending = [], None
    for lvl, title, pg in old_toc:
        if lvl <= 4 and pending is not None:
            new_toc.append([5, "▸ glossed", pending])
            pending = None
        new_toc.append([lvl, title, new0(pg - 1) + 1])
        if lvl == 4:
            pending = glossed_pg.get(Index._clean(title))
    if pending is not None:
        new_toc.append([5, "▸ glossed", pending])

    out = fitz.open(TMP)
    assert out.page_count == N + len(jobs), (out.page_count, N + len(jobs))
    out.set_toc(new_toc)
    out.saveIncr()
    out.close()
    log(f"outline rebuilt: {len(new_toc):,} entries")

    if os.environ.get("STRETCH_VERIFY"):
        log(f"STRETCH_VERIFY set — result at {TMP.name}, INLINE untouched")
        target = TMP
    else:
        os.replace(TMP, INLINE)
        SIDE.unlink(missing_ok=True); CACHE.unlink(missing_ok=True)
        SCRATCH.unlink(missing_ok=True); ARGFILE.unlink(missing_ok=True)
        target = INLINE
        log(f"replaced {INLINE.name}: {N + len(jobs):,} pages (+{len(jobs):,})")

    chk = fitz.open(target)
    e = next(x for x in sb if x.label.startswith("SB 3.23.9"))
    gp = new0(e.stretch4 - 1) + 2
    log(f"SB 3.23.9: glossed page at {gp} | {chk[gp-1].get_text()[:40].strip()!r}")
    log(f"ALL DONE in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
