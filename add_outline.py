"""Give the inline PDF a working outline (bookmarks / table of contents).

qpdf's --pages splice drops the source outline, so the shipped PDF has none. This
rebuilds it from the original book's 58,520 bookmarks with page numbers remapped
to the inline positions, demojibaked for display, plus a child entry under each
verse that jumps to its enhanced (interleaved / enlarged) page. Written back with
an incremental save, so the 693 MB file isn't rewritten.
"""
import bisect
import json
import sys
import time
from pathlib import Path

import fitz

from reader import Index, readable

HERE = Path(__file__).parent
ORIG = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021.pdf"
INLINE = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline.pdf"
INLINE_SIDE = INLINE.with_suffix(".pages.json")
TAIL_SIDE = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_interleaved.pages.json"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def build_toc():
    orig = fitz.open(ORIG)
    oidx = Index.load(ORIG, orig)
    sloka_by_label = {e.label: e.sloka for e in oidx.entries}
    side = json.loads(INLINE_SIDE.read_text())
    enh_by_label = {e[1]: e[4] for e in side["entries"] if e[4] > 0}
    # which enhanced pages are true-interleaved vs enlarged fallbacks (for the label)
    interleaved = set()
    if TAIL_SIDE.exists():
        interleaved = {e[1] for e in json.loads(TAIL_SIDE.read_text())["entries"] if e[4] > 0}

    enhanced_orig = sorted(sloka_by_label[l] - 1 for l in enh_by_label)

    def new0(p):
        return p + bisect.bisect_left(enhanced_orig, p)

    toc, out, seen = orig.get_toc(), [], set()
    for lvl, title, pg in toc:
        out.append([lvl, readable(title), new0(pg - 1) + 1])
        if lvl == 4:
            lab = Index._clean(title)
            if lab in enh_by_label and lab not in seen:
                seen.add(lab)
                kind = "interleaved" if lab in interleaved else "enlarged sloka"
                out.append([5, f"» {kind}", enh_by_label[lab]])
    return out, len(enh_by_label)


def main():
    t0 = time.time()
    toc, n_enh = build_toc()
    log(f"built outline: {len(toc):,} entries ({n_enh:,} verse jump-to-enhanced)")
    doc = fitz.open(INLINE)
    t = time.time()
    doc.set_toc(toc)
    log(f"set_toc: {time.time()-t:.0f}s")
    t = time.time()
    doc.saveIncr()
    log(f"saveIncr: {time.time()-t:.0f}s")

    chk = fitz.open(INLINE)
    got = chk.get_toc()
    log(f"outline now has {len(got):,} entries")
    for lvl, title, pg in got:
        if title.startswith("Canto 1"):
            log(f"  sample: '{title}' -> p{pg}"); break
    log(f"ALL DONE in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
