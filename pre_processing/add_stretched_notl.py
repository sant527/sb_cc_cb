"""Add two 'no-roman' stretched pages after each SB verse's stretched pages.

Same as the stretched reading pages, but with the roman sloka dropped — just the
full-width Devanagari, the word-for-word, and the translation
(`interleave.draw_stretched(..., translit=False)`), one pada per row and two per
row. They are qpdf-spliced right after the verse's existing `▸ stretched (2/row)`
page, so the tail of each SB verse becomes:

    … → stretched(1/row) → stretched(2/row) → stretched-nr(1/row) → stretched-nr(2/row)

Run this after add_stretched.py. Outline gets two `▸ stretched no-roman` children
per verse (new reader modes 5 and 6). Idempotent; STRETCH_VERIFY=1 writes to a
temp file instead of replacing the shipped PDF.
"""
import bisect
import os
import subprocess
import sys
import time
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # for `reader`
from interleave import draw_stretched
from reader import Index

HERE = Path(__file__).resolve().parent.parent
INLINE = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline_interleaved.pdf"
SIDE = INLINE.with_suffix(".pages.json")
CACHE = INLINE.with_suffix(".index.json")
SCRATCH = HERE / ".stretched_nr_pages.pdf"
ARGFILE = HERE / ".qpdf_stretch_nr_args.txt"
TMP = HERE / ".inline_stretch_nr.tmp.pdf"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    t0 = time.time()
    doc = fitz.open(INLINE)
    N = doc.page_count
    old_toc = doc.get_toc()
    if any("no-roman" in t for _, t, _ in old_toc):
        log("outline already has 'no-roman' entries — nothing to do."); return
    idx = Index.load(INLINE, doc)
    sb = [e for e in idx.entries if e.label.startswith("SB ") and e.stretch2 > 0]

    log(f"drawing no-roman pages for {len(sb):,} SB verses...")
    scratch = fitz.open()
    jobs = []                          # (insert_after_0based, s1_scratch, s2_scratch, label)
    for e in sb:
        s0 = e.sloka - 1
        p = doc[s0]
        pg1 = scratch.new_page(-1, width=p.rect.width, height=p.rect.height)
        draw_stretched(pg1, doc, s0, per_row=1, translit=False)
        pg2 = scratch.new_page(-1, width=p.rect.width, height=p.rect.height)
        draw_stretched(pg2, doc, s0, per_row=2, translit=False)
        jobs.append((e.stretch2 - 1, scratch.page_count - 2, scratch.page_count - 1, e.label))
        if len(jobs) % 2000 == 0:
            log(f"  drew {len(jobs):,} verses ({time.time()-t0:.0f}s)")
    scratch.save(str(SCRATCH))
    doc.close()
    jobs.sort()
    inserts = [q for q, _, _, _ in jobs]
    log(f"drew {len(jobs):,} verses ({len(jobs)*2:,} pages) -> {SCRATCH.name}")

    toks, prev = [], 0
    for q, s1, s2, _ in jobs:
        toks += [str(INLINE), f"{prev + 1}-{q + 1}"]
        toks += [str(SCRATCH), str(s1 + 1), str(SCRATCH), str(s2 + 1)]
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
        return p + 2 * bisect.bisect_left(inserts, p)

    stretch_nr = {lab: new0(q) + 2 for q, _, _, lab in jobs}

    new_toc, pending = [], None
    for lvl, title, pg in old_toc:
        if lvl <= 4 and pending is not None:
            new_toc.append([5, "▸ stretched no-roman (big)", pending])
            new_toc.append([5, "▸ stretched no-roman (2/row)", pending + 1])
            pending = None
        new_toc.append([lvl, title, new0(pg - 1) + 1])
        if lvl == 4:
            pending = stretch_nr.get(Index._clean(title))
    if pending is not None:
        new_toc.append([5, "▸ stretched no-roman (big)", pending])
        new_toc.append([5, "▸ stretched no-roman (2/row)", pending + 1])

    out = fitz.open(TMP)
    assert out.page_count == N + 2 * len(jobs), (out.page_count, N + 2 * len(jobs))
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
        log(f"replaced {INLINE.name}: {N + 2*len(jobs):,} pages (+{2*len(jobs):,})")

    chk = fitz.open(target)
    e = next(x for x in jobs if x[3].startswith("SB 4.4.24"))
    p1 = new0(e[0]) + 2
    log(f"SB 4.4.24: no-roman pages at {p1} and {p1+1}")
    for pno in (p1, p1 + 1):
        head = chk[pno - 1].get_text()[:40].replace("\n", " ")
        log(f"  p.{pno}: {head!r}")
    log(f"ALL DONE in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
