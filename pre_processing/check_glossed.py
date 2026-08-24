"""Scan every SB glossed verse and flag the ones whose alignment still looks off,
so problems can be found in bulk instead of one at a time while reading.

For each verse it reproduces exactly what draw_glossed would place (main aligner,
then the degenerate -> order-free fallback, then the lopsided -> order-free
switch) and scores the result:

  EMPTY   a Devanagari line got no gloss while the verse has plenty of words
  LOWBAL  the least-filled line has < 0.5 of the most-filled (a pile)
  PILE    most of a line's glosses collapse into a narrow x-band
  DROP    many word-for-word entries never got placed (>35% missing)

Prints the flagged verses worst-first. Run:  uv run python pre_processing/check_glossed.py
"""
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from interleave import (classify_lines, _parse_wff, _align_glosses, _align_glosses_oi,
                        _gloss_degenerate, _line_balance, _below_split,
                        leading_attributions, WRAP_MAX_FRAC)
from reader import Index, readable

SRC = Path(__file__).resolve().parent / "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021.pdf"


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


def wff_and_tt(page, d, tl, tt):
    """Exactly as draw_glossed: merge wrapped padas, find the translation boundary
    by font (via _below_split), and parse the word-for-word from the region above."""
    tt2 = merged_tt(tt, tl)
    W = page.rect.width
    vb = max(r.y1 for r in d + tl)
    _below_all, ttop = _below_split(page, vb)
    ent = _parse_wff(page.get_text(clip=fitz.Rect(0, vb + 1, W, ttop - 1)).replace("\n", " "))
    return tt2, ent


def final_place(ent, tt2, ndeva):
    """Reproduce draw_glossed's placement choice exactly."""
    place = _align_glosses(ent, tt2, ndeva, readable)
    if place is None:
        return None
    if _gloss_degenerate(place):
        place = _align_glosses_oi(ent, tt2, ndeva, readable)
        if place is None or _gloss_degenerate(place):
            return None
        return place
    a = max(min(leading_attributions(tt2), ndeva - 1, len(tt2) - 1), 0)
    body = [len(x) for x in place[a:]]
    if body and (min(body) == 0 or (max(body) and min(body) / max(body) < 0.6)):
        oi = _align_glosses_oi(ent, tt2, ndeva, readable)
        if oi is not None and not _gloss_degenerate(oi):
            bo = [len(x) for x in oi[a:]]
            score = lambda b: sum(b) - (max(b) - min(b)) if b else 0
            if score(bo) > score(body) and sum(bo) >= 0.7 * sum(body):
                place = oi
    return place


def flags_for(place, n_entries, a):
    """a = number of leading attribution lines (… uvāca), which are legitimately
    short and are peeled before judging balance/emptiness."""
    body = [len(x) for x in place[a:]]                 # ignore the attribution line(s)
    total = sum(body)
    fl = []
    if body and total >= len(body) and min(body) == 0:      # a real verse line with no gloss
        fl.append("EMPTY")
    if body and max(body) and min(body) / max(body) < 0.4:  # badly lopsided (a pile)
        fl.append("LOWBAL")
    if n_entries and sum(len(x) for x in place) / n_entries < 0.6:   # many words unplaced
        fl.append("DROP")
    return fl


def main():
    doc = fitz.open(SRC)
    idx = Index.load(SRC, doc)
    sb = [e for e in idx.entries if e.label.startswith("SB ")]
    rows = []
    for e in sb:
        d, tl, tt, _ = classify_lines(doc[e.sloka - 1])
        if not d or not tt:
            continue
        tt2, ent = wff_and_tt(doc[e.sloka - 1], d, tl, tt)
        if not ent:
            continue
        place = final_place(ent, tt2, len(d))
        if place is None:                              # a repeat page — nothing to check
            continue
        a = max(min(leading_attributions(tt2), len(d) - 1, len(tt2) - 1), 0)
        fl = flags_for(place, len(ent), a)
        if fl:
            rows.append((len(fl), _line_balance(place), e.label.split(" /")[0],
                         [len(x) for x in place], len(ent), fl))
    order = {"EMPTY": 0, "DROP": 1, "LOWBAL": 2}
    rows.sort(key=lambda r: (-r[0], min(order.get(f, 9) for f in r[5]), r[1]))
    print(f"{len(rows)} glossed verses flagged (of {len(sb):,} SB verses):\n")
    for nf, bal, lab, counts, ne, fl in rows:
        print(f"  {lab:16} lines={counts} entries={ne} bal={bal:.2f}  {' '.join(fl)}")


if __name__ == "__main__":
    sys.exit(main())
