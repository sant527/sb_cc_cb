"""Add two full-width stretched reading pages after each SB verse.

For every SB verse with Devanagari, this draws two `interleave.draw_stretched`
pages — one pada per row (big) and two padas per row (couplet) — with the
Devanagari scaled to fill the page width and trailing dandas / verse numbers
stripped. They are qpdf-spliced in right after the verse's existing enhanced
page(s), so the order becomes:

    sloka -> [clubbed] -> large/enlarged -> stretched(1/row) -> stretched(2/row)

Only SB verses (CC/CB have no Devanagari). Page count grows by 2 per verse; the
outline is remapped and gets `▸ stretched` children (the reader ignores those and
just reaches the pages by paging forward). Idempotent: refuses to run if the
outline already has stretched entries. STRETCH_VERIFY=1 leaves the result at a
temp file without replacing the shipped PDF.
"""
import bisect
import os
import subprocess
import sys
import time
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # for `reader`
from interleave import classify_lines, draw_stretched
from reader import Index

HERE = Path(__file__).resolve().parent.parent
INLINE = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline_interleaved.pdf"
SIDE = INLINE.with_suffix(".pages.json")
CACHE = INLINE.with_suffix(".index.json")
SCRATCH = HERE / ".stretched_pages.pdf"
ARGFILE = HERE / ".qpdf_stretch_args.txt"
TMP = HERE / ".inline_stretch.tmp.pdf"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    t0 = time.time()
    doc = fitz.open(INLINE)
    N = doc.page_count
    old_toc = doc.get_toc()
    if any(t.lstrip().startswith("▸ stretched") for _, t, _ in old_toc):
        log("outline already has '▸ stretched' entries — nothing to do."); return
    idx = Index.load(INLINE, doc)
    sb = [e for e in idx.entries if e.label.startswith("SB ")]

    log(f"drawing stretched pages for up to {len(sb):,} SB verses...")
    scratch = fitz.open()
    jobs = []                          # (insert_after_0based, s1_scratch, s2_scratch, label)
    for e in sb:
        s0 = e.sloka - 1
        if not classify_lines(doc[s0])[0]:      # no Devanagari (4 SB verses) -> skip
            continue
        p = doc[s0]
        pg1 = scratch.new_page(-1, width=p.rect.width, height=p.rect.height)
        draw_stretched(pg1, doc, s0, per_row=1)
        pg2 = scratch.new_page(-1, width=p.rect.width, height=p.rect.height)
        draw_stretched(pg2, doc, s0, per_row=2)
        last_enh = (e.large if e.large > 0 else e.interleaved) - 1   # 0-based
        if last_enh < 0:
            last_enh = s0                        # no enhanced page: sit after the sloka
        jobs.append((last_enh, scratch.page_count - 2, scratch.page_count - 1, e.label))
        if len(jobs) % 2000 == 0:
            log(f"  drew {len(jobs):,} verses ({time.time()-t0:.0f}s)")
    scratch.save(str(SCRATCH))
    doc.close()
    jobs.sort()
    inserts = [q for q, _, _, _ in jobs]         # 0-based positions we insert 2 pages after
    log(f"drew {len(jobs):,} verses ({len(jobs)*2:,} pages) -> {SCRATCH.name}")

    # qpdf: original runs, each verse's 2 stretched pages after its last enhanced page
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

    def new0(p):                                  # each insert adds 2 pages after `q`
        return p + 2 * bisect.bisect_left(inserts, p)

    # new page (1-based) of each verse's first stretched page, keyed by label
    stretch_pg = {lab: new0(q) + 2 for q, _, _, lab in jobs}

    # rebuild outline: remap pages, add two '▸ stretched' children per verse
    new_toc, pending = [], None
    for lvl, title, pg in old_toc:
        if lvl <= 4 and pending is not None:      # flush before the next verse/section
            new_toc.append([5, "▸ stretched (big)", pending])
            new_toc.append([5, "▸ stretched (2/row)", pending + 1])
            pending = None
        new_toc.append([lvl, title, new0(pg - 1) + 1])
        if lvl == 4:
            pending = stretch_pg.get(Index._clean(title))
    if pending is not None:
        new_toc.append([5, "▸ stretched (big)", pending])
        new_toc.append([5, "▸ stretched (2/row)", pending + 1])

    out = fitz.open(TMP)
    assert out.page_count == N + 2 * len(jobs), (out.page_count, N + 2 * len(jobs))
    out.set_toc(new_toc)
    out.saveIncr()
    out.close()
    log(f"outline rebuilt: {len(new_toc):,} entries")

    verify = bool(os.environ.get("STRETCH_VERIFY"))
    if verify:
        log(f"STRETCH_VERIFY set — result at {TMP.name}, INLINE untouched")
        target = TMP
    else:
        os.replace(TMP, INLINE)
        SIDE.unlink(missing_ok=True); CACHE.unlink(missing_ok=True)
        SCRATCH.unlink(missing_ok=True); ARGFILE.unlink(missing_ok=True)
        target = INLINE
        log(f"replaced {INLINE.name}: {N + 2*len(jobs):,} pages (+{2*len(jobs):,})")

    # sanity: dump a verse's page sequence
    chk = fitz.open(target)
    e = next(x for x in jobs if x[3].startswith("SB 4.4.24"))
    p1 = new0(e[0]) + 2
    log(f"SB 4.4.24: stretched pages at {p1} and {p1+1}")
    for pno in (p1, p1 + 1):
        head = chk[pno - 1].get_text()[:40].replace("\n", " ")
        log(f"  p.{pno}: {head!r}")
    log(f"ALL DONE in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
