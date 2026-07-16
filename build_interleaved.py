"""Build the drop-in interleaved PDF (append-at-tail + incremental save).

Middle-insertion into a 237k-page tree is O(n) per insert and thrashes, so instead
we copy the original, APPEND every interleaved page at the END (O(1) each), and
saveIncr() so the original 538 MB is not rewritten. Originals keep their page
numbers; the new pages sit at the tail. A sidecar index (<out>.pages.json) maps
every verse to its translation / sloka / interleaved page, which reader.py loads
to navigate — the interleaved page need not be physically next to the sloka.
"""
import json
import shutil
import sys
import time
from pathlib import Path

import fitz

from interleave import draw_interleaved, is_transformable
from reader import Index

HERE = Path(__file__).parent
SRC = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021.pdf"
OUT = HERE / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_interleaved.pdf"
SIDE = OUT.with_suffix(".pages.json")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    t0 = time.time()
    src = fitz.open(SRC)
    idx = Index.load(SRC, src)
    verses = idx.entries
    N = src.page_count
    sb = [e for e in verses if e.label.startswith("SB ")]

    log(f"scanning {len(sb):,} SB verses...")
    S = sorted({e.sloka - 1 for e in sb if is_transformable(src, e.sloka - 1)})
    log(f"{len(S):,} interleaved pages ({100*len(S)//max(1,len(sb))}% of SB verses)")

    log("copying original -> output...")
    shutil.copy(SRC, OUT)
    doc = fitz.open(OUT)

    log(f"appending {len(S):,} interleaved pages at the tail...")
    rank = {}
    for j, s in enumerate(S):
        page = doc.new_page(-1, width=src[s].rect.width, height=src[s].rect.height)
        draw_interleaved(page, src, s)
        rank[s] = N + j                       # 0-indexed position of this new page
        if j % 3000 == 0 and j:
            log(f"  appended {j:,}/{len(S):,} ({time.time()-t0:.0f}s)")
    log(f"appended all; saving incrementally...")
    doc.saveIncr()
    mb = OUT.stat().st_size / 1e6
    log(f"saved {OUT.name} ({mb:.0f} MB, {doc.page_count:,} pages)")

    # sidecar: originals keep their numbers; interleaved is a tail page (1-indexed)
    entries = []
    for e in verses:
        inter = rank[e.sloka - 1] + 1 if (e.sloka - 1) in rank else -1
        entries.append([e.page, e.label, e.chapter, e.sloka, inter])
    SIDE.write_text(json.dumps({"pdf": OUT.name, "pages": doc.page_count, "entries": entries}))
    log(f"wrote {SIDE.name} ({len(entries):,} verses)")

    # sanity
    chk = fitz.open(OUT)
    assert chk.page_count == N + len(S), (chk.page_count, N + len(S))
    for label in ("SB 10.44.6", "SB 1.1.1", "SB 1.1.4"):
        e = next(x for x in entries if x[1].startswith(label + " "))
        head = chk[e[4] - 1].get_text()[:48].replace("\n", " ") if e[4] > 0 else "(none)"
        log(f"  {label}: trans p.{e[0]} sloka p.{e[3]} inter p.{e[4]} | {head!r}")
    log(f"ALL DONE in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
