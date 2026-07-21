"""Build the shippable INLINE PDF with qpdf.

Each SB verse's enhanced page (interleaved, or an enlarged-sloka fallback) is
placed physically right after its sloka page, in reading order; CC/CB untouched.

PyMuPDF and pikepdf both assemble/reorder a 250k-page tree in O(n^2) (hours).
qpdf does reference-based page assembly in C++ (O(n)). We reuse the already-drawn
interleaved pages from the current tail build and draw only the enlarged
fallbacks, then let qpdf splice everything via a --pages job.
"""
import bisect
import json
import subprocess
import sys
import time
from pathlib import Path

import fitz

from interleave import classify_lines, draw_enlarged_sloka, is_transformable
from reader import Index

HERE = Path(__file__).parent
SRC = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021.pdf"
CUR = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_interleaved.pdf"          # tail build (reuse)
CUR_SIDE = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_interleaved.pages.json"
EXTRA = HERE / ".enlarged_pages.pdf"                                     # scratch
ARGFILE = HERE / ".qpdf_args.txt"                                        # scratch
OUT = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline.pdf"
OUT_SIDE = OUT.with_suffix(".pages.json")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    t0 = time.time()
    src = fitz.open(SRC)
    idx = Index.load(SRC, src)
    cur_side = json.loads(CUR_SIDE.read_text())
    inter_tail = {e[3] - 1: e[4] - 1 for e in cur_side["entries"] if e[4] > 0}  # sloka0 -> tail0

    sb = [e for e in idx.entries if e.label.startswith("SB ")]
    log(f"scanning {len(sb):,} SB verses...")
    enlarged = []
    for e in sb:
        s = e.sloka - 1
        if s in inter_tail:
            continue
        if classify_lines(src[s])[0] and not is_transformable(src, s):
            enlarged.append(s)
    enlarged.sort()

    extra = fitz.open()
    extra_rank = {}
    for j, s in enumerate(enlarged):
        pg = extra.new_page(-1, width=src[s].rect.width, height=src[s].rect.height)
        draw_enlarged_sloka(pg, src, s)
        extra_rank[s] = j
    extra.save(str(EXTRA))
    log(f"interleaved (reused): {len(inter_tail):,}  |  enlarged (drawn): {len(extra_rank):,}")

    enhanced = sorted(set(inter_tail) | set(extra_rank))   # 0-indexed sloka pages
    N_orig = src.page_count

    # qpdf --pages job: alternate runs of the original with each enhanced page,
    # pulled from CUR (interleaved) or EXTRA (enlarged). 1-indexed page numbers.
    toks = []
    prev = 0                                    # 0-indexed next original page to emit
    for s in enhanced:
        toks += [str(SRC), f"{prev + 1}-{s + 1}"]           # originals up to & incl sloka
        if s in inter_tail:
            toks += [str(CUR), str(inter_tail[s] + 1)]
        else:
            toks += [str(EXTRA), str(extra_rank[s] + 1)]
        prev = s + 1
    toks += [str(SRC), f"{prev + 1}-{N_orig}"]              # tail originals
    ARGFILE.write_text("\n".join(toks) + "\n")
    log(f"qpdf job: {len(enhanced):,} enhanced pages spliced; running qpdf...")

    ts = time.time()
    subprocess.run(
        ["qpdf", "--warning-exit-0", "--empty", "--pages", f"@{ARGFILE}", "--", str(OUT)],
        check=True)
    log(f"qpdf assembled + wrote {OUT.name} in {time.time()-ts:.0f}s "
        f"({OUT.stat().st_size/1e6:.0f} MB)")

    # inline sidecar
    S = enhanced
    def new0(p):
        return p + bisect.bisect_left(S, p)
    enh_set = set(enhanced)
    entries = []
    for e in idx.entries:
        trans = new0(e.page - 1) + 1
        sloka = new0(e.sloka - 1) + 1
        enhanced_pg = sloka + 1 if (e.sloka - 1) in enh_set else -1
        entries.append([trans, e.label, e.chapter, sloka, enhanced_pg])
    total = N_orig + len(enhanced)
    OUT_SIDE.write_text(json.dumps(
        {"pdf": OUT.name, "pages": total, "layout": "inline", "entries": entries}))
    log(f"wrote {OUT_SIDE.name}")

    # working outline: original bookmarks remapped + a jump-to-enhanced per verse
    from add_outline import build_toc
    toc, n_jump = build_toc()
    doc = fitz.open(OUT)
    doc.set_toc(toc)
    doc.saveIncr()
    log(f"outline: {len(toc):,} entries ({n_jump:,} verse jump-to-enhanced)")

    chk = fitz.open(OUT)
    log(f"output pages: {chk.page_count:,} (expected {total:,})")
    assert chk.page_count == total, (chk.page_count, total)
    for lab in ("SB 1.2.1", "SB 1.1.6", "SB 10.44.6", "Madhya 20.268"):
        e = next(x for x in entries if x[1].startswith(lab + " "))
        if e[4] > 0:
            role = chk[e[4]-1].get_text()[:32].replace("\n", " ")
        else:
            role = "(no enhanced page)"
        log(f"  {lab}: sloka p.{e[3]} enhanced p.{e[4]} | {role!r}")
    EXTRA.unlink(missing_ok=True)
    ARGFILE.unlink(missing_ok=True)
    log(f"ALL DONE in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
