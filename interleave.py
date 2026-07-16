"""Interleave Devanagari + transliteration for SB sloka pages.

A sloka page groups all Devanagari lines, then all transliteration lines. This
rebuilds the verse so each transliteration pada sits directly above the
Devanagari that renders it, with the Devanagari enlarged. When one Devanagari
line holds k padas (older cantos pack 2 padas/line), that group's k
transliteration padas share one row joined by ' // '.

Glyphs are copied as vectors via Page.show_pdf_page(clip=...), so the custom
Devanagari fonts (RM Devanagari in canto 10, Indevr elsewhere) need no decoding
and the text stays selectable.
"""
from __future__ import annotations

import fitz

LATIN = ("ScaGoudy", "CMR", "CMSL", "CMMI", "CMTI")

DEVA_SCALE = 1.5     # enlarge Devanagari glyphs (native ~13pt -> ~19pt)
TL_SCALE = 1.0       # leave transliteration at its native ~17pt
SIDE_MARGIN = 24     # keep enlarged lines off the page edges
VERSE_GAP = 6        # vertical gap between interleaved rows
BELOW_GAP = 14       # gap before the word-for-word / translation block

SEP = " // "         # separator between side-by-side transliteration padas
SEP_FONT = "times-italic"
SEP_COLOR = (0.12, 0.12, 0.12)

CLIP_EDGE_PAD = 4.0  # top/bottom padding for the first/last Devanagari clip


def classify_lines(page):
    """Group spans into visual lines; return (devanagari_bboxes, translit_bboxes)."""
    rows = {}
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                if sp["text"].strip():
                    rows.setdefault(round(sp["bbox"][1]), []).append(sp)
    deva, tl = [], []
    for y in sorted(rows):
        spans = rows[y]
        bbox = fitz.Rect(min(s["bbox"][0] for s in spans), min(s["bbox"][1] for s in spans),
                         max(s["bbox"][2] for s in spans), max(s["bbox"][3] for s in spans))
        size = max(s["size"] for s in spans)
        if any(not s["font"].startswith(LATIN) for s in spans):
            deva.append(bbox)
        elif any("Italic" in s["font"] for s in spans) and size >= 16:
            tl.append(bbox)
    return deva, tl


WRAP_MAX_FRAC = 0.55     # a transliteration line this much narrower than the
                         # widest is treated as a wrapped continuation (e.g. the
                         # lone "dhimahi" tail of a long pada)


def _group_padas(tl):
    """Fold short wrapped-continuation lines back into the pada they belong to.
    Returns a list of padas, each a list of one or more line bboxes."""
    full = max(b.width for b in tl)
    padas = [[tl[0]]]
    for b in tl[1:]:
        if b.width < WRAP_MAX_FRAC * full:      # a wrap tail -> stays with its pada
            padas[-1].append(b)
        else:
            padas.append([b])
    return padas


def _rows_for(deva, padas):
    """Build interleaved rows from Devanagari lines and transliteration padas
    (each pada = list of physical line bboxes). None if counts don't pair."""
    a, p = len(deva), len(padas)
    if a == 0 or p == 0:
        return None
    rows = []
    if p % a == 0:                       # 1 deva line <-> k transliteration padas
        k = p // a
        for i in range(a):
            grp = padas[i * k:(i + 1) * k]
            if k == 1:                   # single pada: its wrap lines stacked
                for bb in grp[0]:
                    rows.append([("clip", bb, TL_SCALE)])
            else:                        # several padas share the deva line -> side by side
                row = []
                for j, pada in enumerate(grp):
                    if j:
                        row.append(("sep",))
                    row += [("clip", bb, TL_SCALE) for bb in pada]
                rows.append(row)
            rows.append([("clip", deva[i], DEVA_SCALE)])
        return rows
    if a % p == 0:                       # reverse (not seen in SB) -> stacked
        k = a // p
        for i in range(p):
            rows += [[("clip", bb, TL_SCALE)] for bb in padas[i]]
            rows += [[("clip", dv, DEVA_SCALE)] for dv in deva[i * k:(i + 1) * k]]
        return rows
    return None


def expand_deva(deva):
    """Grow each Devanagari clip vertically to the midpoint of the gap to its
    neighbours. The reported metric box omits below-baseline vowel marks (worst
    in RM Devanagari, canto 10), so clipping to it slices descenders; tiling the
    inter-line gaps captures the full glyph without grabbing the next line."""
    out = []
    for i, bb in enumerate(deva):
        top = (deva[i - 1].y1 + bb.y0) / 2 if i > 0 else bb.y0 - CLIP_EDGE_PAD
        bot = (bb.y1 + deva[i + 1].y0) / 2 if i < len(deva) - 1 else bb.y1 + CLIP_EDGE_PAD
        out.append(fitz.Rect(bb.x0, top, bb.x1, bot))
    return out


def verse_rows(deva, tl):
    """Ordered rows for the interleaved verse, or None if not cleanly pairable.

    A row is a list of ("clip", bbox, scale) / ("sep",) segments on one baseline.
    Tries the straight one-line-per-pada pairing first (the common case); only if
    that doesn't pair does it merge wrapped continuation lines and retry.
    """
    if not deva or not tl:
        return None
    rows = _rows_for(deva, [[t] for t in tl])
    if rows is not None:
        return rows
    return _rows_for(deva, _group_padas(tl))


def is_transformable(src, pno):
    return verse_rows(*classify_lines(src[pno])) is not None


def _render_row(new, src, pno, row, y, max_w):
    clips = [seg for seg in row if seg[0] == "clip"]
    n_sep = sum(1 for seg in row if seg[0] == "sep")
    base_sz = 17 * TL_SCALE
    sep_w = fitz.get_text_length(SEP, fontname=SEP_FONT, fontsize=base_sz)
    nat_w = sum(bb.width * sc for _, bb, sc in clips) + sep_w * n_sep
    fit = min(1.0, max_w / nat_w) if nat_w > max_w else 1.0
    row_h = max(bb.height * sc for _, bb, sc in clips) * fit

    x = (new.rect.width - nat_w * fit) / 2
    for seg in row:
        if seg[0] == "sep":
            new.insert_text((x, y + row_h * 0.72), SEP, fontname=SEP_FONT,
                            fontsize=base_sz * fit, color=SEP_COLOR)
            x += sep_w * fit
        else:
            _, bb, sc = seg
            w, h = bb.width * sc * fit, bb.height * sc * fit
            new.show_pdf_page(fitz.Rect(x, y, x + w, y + h), src, pno, clip=bb)
            x += w
    return row_h


def draw_interleaved(new, src, pno):
    """Draw the interleaved verse (header, verse, word-for-word + translation)
    onto page `new`, copying vector content from src[pno]. Returns False (drawing
    nothing) if the verse isn't cleanly pairable."""
    page = src[pno]
    W, H = page.rect.width, page.rect.height
    deva, tl = classify_lines(page)
    deva = expand_deva(deva)                     # capture full Devanagari ink
    rows = verse_rows(deva, tl)
    if rows is None:
        return False

    verse_top = min(r.y0 for r in deva + tl)
    verse_bot = max(r.y1 for r in deva + tl)

    below = [sp["bbox"] for b in page.get_text("dict")["blocks"]
             for ln in b.get("lines", []) for sp in ln["spans"]
             if sp["text"].strip() and sp["bbox"][1] > verse_bot + 1 and sp["bbox"][3] < H - 30]

    new.show_pdf_page(fitz.Rect(0, 0, W, verse_top), src, pno,
                      clip=fitz.Rect(0, 0, W, verse_top))            # header

    max_w = W - 2 * SIDE_MARGIN
    y = verse_top
    for row in rows:
        y += _render_row(new, src, pno, row, y, max_w) + VERSE_GAP

    if below:
        top = min(r[1] for r in below) - 2
        bot = max(r[3] for r in below) + 2
        y += BELOW_GAP
        new.show_pdf_page(fitz.Rect(0, y, W, y + (bot - top)), src, pno,
                          clip=fitz.Rect(0, top, W, bot))
    return True
