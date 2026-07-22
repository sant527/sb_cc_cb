"""Add a clubbed (two-padas-per-line) page to each clubbable SB verse.

Runs on the finished inline PDF. For every verse whose Devanagari is printed one
pada per line (see interleave.is_clubbable — ~6,980 verses, mostly cantos 10-12),
this draws a compact couplet page and splices it right after the sloka, *before*
the existing enlarged 1-pada/line page:

    sloka -> clubbed (compact, 2 padas/line) -> large (enlarged, 1 pada/line)

The clubbed page becomes the verse's primary enhanced page (what the reader jumps
to); the enlarged page stays as the "read large" page one step further on. As in
build_inline.py, qpdf does the reference-based splice (O(n); PyMuPDF/pikepdf are
O(n^2) here). The outline is rebuilt with a `» clubbed` and a `»» read large`
child per clubbed verse; other verses keep their single `»` child.

Idempotent guard: refuses to run if the outline already has `» clubbed` entries.
"""
import bisect
import os
import subprocess
import sys
import time
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # for `reader`
from interleave import draw_clubbed, is_clubbable
from reader import Index

HERE = Path(__file__).resolve().parent.parent   # PDFs live in the project root
INLINE = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline_interleaved.pdf"
SIDE = INLINE.with_suffix(".pages.json")
CACHE = INLINE.with_suffix(".index.json")
EXTRA = HERE / ".clubbed_pages.pdf"                                # scratch
ARGFILE = HERE / ".qpdf_club_args.txt"                             # scratch
TMP = HERE / ".inline_clubbed.tmp.pdf"                             # scratch output


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    t0 = time.time()
    doc = fitz.open(INLINE)
    old_toc = doc.get_toc()
    if any(t.lstrip().startswith("» clubbed") for _, t, _ in old_toc):
        log("outline already has '» clubbed' entries — nothing to do."); return
    N = doc.page_count
    idx = Index.load(INLINE, doc)
    sb = [e for e in idx.entries if e.label.startswith("SB ")]

    log(f"scanning {len(sb):,} SB verses for clubbable ones...")
    clubbable = [e for e in sb if is_clubbable(doc, e.sloka - 1)]
    clubbable_labels = {e.label for e in clubbable}
    S = sorted(e.sloka - 1 for e in clubbable)            # 0-based sloka pages
    log(f"{len(S):,} clubbable verses ({100*len(S)//max(1,len(sb))}% of SB)")

    # draw the clubbed pages into a scratch PDF (content is copied in, so the
    # scratch file is self-contained once saved)
    log("drawing clubbed pages...")
    extra = fitz.open()
    rank = {}
    for j, s in enumerate(S):
        p = doc[s]
        pg = extra.new_page(-1, width=p.rect.width, height=p.rect.height)
        if not draw_clubbed(pg, doc, s):
            raise RuntimeError(f"draw_clubbed failed for sloka page {s}")
        rank[s] = j
        if j % 2000 == 0 and j:
            log(f"  drew {j:,}/{len(S):,} ({time.time()-t0:.0f}s)")
    extra.save(str(EXTRA))
    doc.close()
    log(f"drew {len(S):,} clubbed pages -> {EXTRA.name}")

    # qpdf job: original runs interleaved with each clubbed page (after its sloka)
    toks, prev = [], 0
    for s in S:
        toks += [str(INLINE), f"{prev + 1}-{s + 1}"]     # originals up to & incl sloka
        toks += [str(EXTRA), str(rank[s] + 1)]           # the clubbed page
        prev = s + 1
    toks += [str(INLINE), f"{prev + 1}-{N}"]             # tail
    ARGFILE.write_text("\n".join(toks) + "\n")
    log("running qpdf splice...")
    ts = time.time()
    subprocess.run(
        ["qpdf", "--warning-exit-0", "--empty", "--pages", f"@{ARGFILE}", "--", str(TMP)],
        check=True)
    log(f"qpdf wrote {TMP.name} in {time.time()-ts:.0f}s")

    # remap: a clubbed page inserted after sloka s shifts every later original page
    def new0(p):
        return p + bisect.bisect_left(S, p)

    # rebuild the outline: remap pages; for a clubbed verse, turn its single `»`
    # child into `» clubbed` (the new page) + `»» read large` (the enlarged page)
    new_toc, last_clubbable = [], False
    for lvl, title, pg in old_toc:
        npg = new0(pg - 1) + 1
        if lvl == 5 and title.lstrip().startswith("»") and last_clubbable:
            new_toc.append([5, "» clubbed", npg - 1])    # inserted right before large
            new_toc.append([5, "»» read large", npg])
            last_clubbable = False
            continue
        new_toc.append([lvl, title, npg])
        last_clubbable = (lvl == 4 and Index._clean(title) in clubbable_labels)

    out = fitz.open(TMP)
    assert out.page_count == N + len(S), (out.page_count, N + len(S))
    out.set_toc(new_toc)
    out.saveIncr()
    out.close()
    log(f"outline rebuilt: {len(new_toc):,} entries; {len(S):,} verses clubbed")

    verify = bool(os.environ.get("CLUB_VERIFY"))
    if not verify:
        os.replace(TMP, INLINE)
        SIDE.unlink(missing_ok=True)  # stale; reader rebuilds from the new outline
        CACHE.unlink(missing_ok=True)
        EXTRA.unlink(missing_ok=True)
        ARGFILE.unlink(missing_ok=True)
        target = INLINE
    else:
        log(f"CLUB_VERIFY set — left result at {TMP.name}, INLINE untouched")
        target = TMP

    # sanity: show a clubbed verse's sloka -> clubbed -> large trio
    chk = fitz.open(target)
    log(f"output pages: {chk.page_count:,} (was {N:,}, +{len(S):,})")
    e = next((x for x in clubbable if x.label.startswith("SB 10.44.6")), clubbable[0])
    s_new = new0(e.sloka - 1) + 1
    for label, pno in (("sloka", s_new), ("clubbed", s_new + 1), ("large", s_new + 2)):
        head = chk[pno - 1].get_text()[:40].replace("\n", " ")
        log(f"  {e.label} {label:>7} p.{pno} | {head!r}")
    for lvl, title, pg in chk.get_toc():
        if lvl in (4, 5) and e.label.split(' /')[0] in title and pg >= s_new - 1:
            log(f"    toc L{lvl}: {title!r} -> p.{pg}")
            if lvl == 5 and "read large" in title:
                break
    log(f"ALL DONE in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
