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

import re

import fitz
import numpy as np

LATIN = ("ScaGoudy", "CMR", "CMSL", "CMMI", "CMTI")

# Speaker attribution ("vyäsa uväca", "çré-bhagavän uväca", ...): its own line
# that pairs 1:1, sitting above the verse proper.
ATTRIB_RE = re.compile(r"uv[aä]ca\b", re.IGNORECASE)

DEVA_SCALE = 1.5     # enlarge Devanagari glyphs (native ~13pt -> ~19pt)
TL_SCALE = 1.0       # leave transliteration at its native ~17pt
SIDE_MARGIN = 24     # keep enlarged lines off the page edges
CLUB_MARGIN = 12     # tighter side margin for clubbed (2-padas/line) pages
VERSE_GAP = 6        # vertical gap between interleaved rows
BELOW_GAP = 14       # gap before the word-for-word / translation block
DEVA_GAP = 16        # horizontal gap between two clubbed Devanagari padas

SEP = " // "         # separator between side-by-side transliteration padas
SEP_FONT = "times-italic"
SEP_COLOR = (0.12, 0.12, 0.12)

CLIP_EDGE_PAD = 4.0  # top/bottom padding for the first/last Devanagari clip


def classify_lines(page):
    """Group spans into visual lines.

    Returns (devanagari_bboxes, translit_bboxes, tl_texts, is_rm). `tl_texts` is
    the transliteration line strings (parallel to translit_bboxes). `is_rm` is
    True when the Devanagari uses the RM Devanagari font (cantos 10-12), whose
    metric box omits descenders; Indevr (cantos 1-9) reports them accurately.
    """
    rows = {}
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                if sp["text"].strip():
                    rows.setdefault(round(sp["bbox"][1]), []).append(sp)
    deva, tl, tl_texts = [], [], []
    is_rm = False
    for y in sorted(rows):
        spans = rows[y]
        bbox = fitz.Rect(min(s["bbox"][0] for s in spans), min(s["bbox"][1] for s in spans),
                         max(s["bbox"][2] for s in spans), max(s["bbox"][3] for s in spans))
        size = max(s["size"] for s in spans)
        if any(not s["font"].startswith(LATIN) for s in spans):
            deva.append(bbox)
            if any("Devanagari" in s["font"] for s in spans):   # 'RM Devanagari'
                is_rm = True
        elif any("Italic" in s["font"] for s in spans) and size >= 16:
            tl.append(bbox)
            tl_texts.append("".join(s["text"] for s in spans).strip())
    return deva, tl, tl_texts, is_rm


def leading_attributions(tl_texts):
    """How many leading transliteration lines are speaker attributions."""
    n = 0
    for t in tl_texts:
        if ATTRIB_RE.search(t):
            n += 1
        else:
            break
    return n


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


def _ink_runs(page, deva, zoom=6):
    """Pixel-scan the Devanagari block; return one (ink_top, ink_bottom) run per
    line. Metric boxes can't be trusted here, but the whitespace between lines is
    directly observable."""
    x0 = min(b.x0 for b in deva)
    x1 = max(b.x1 for b in deva)
    top = deva[0].y0 - 10
    bot = deva[-1].y1 + 12
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False,
                          clip=fitz.Rect(x0, top, x1, bot))
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).mean(2)
    ink = (img < 128).any(axis=1)
    runs, y = [], 0
    while y < len(ink):
        if ink[y]:
            s = y
            while y < len(ink) and ink[y]:
                y += 1
            runs.append((top + s / zoom, top + (y - 1) / zoom))
        else:
            y += 1
    return runs


def expand_deva(page, deva):
    """Grow each Devanagari clip to the middle of the real whitespace around it.

    The metric box omits below-baseline vowel marks (RM Devanagari, cantos 10-12),
    so clipping to it slices descenders — and cutting at the *metric* midpoint is
    no better: it lands above the true whitespace, so the sliced ink lands inside
    the next line's clip and reappears as a ghost. Cutting in the measured
    whitespace band captures each line whole with nothing bleeding across.
    """
    if not deva:
        return deva

    def _metric_midpoints():
        return [fitz.Rect(bb.x0,
                          (deva[i - 1].y1 + bb.y0) / 2 if i else bb.y0 - CLIP_EDGE_PAD,
                          bb.x1,
                          (bb.y1 + deva[i + 1].y0) / 2 if i < len(deva) - 1
                          else bb.y1 + CLIP_EDGE_PAD)
                for i, bb in enumerate(deva)]

    runs = _ink_runs(page, deva)
    # Assign each run to the line it overlaps *most*. Plain overlap is too loose:
    # a descender can reach past the next line's metric top, which would merge two
    # lines into one. This also drops runs from the header/transliteration that the
    # scan window catches, and merges a line whose ink splits into several runs.
    ink: list[tuple[float, float] | None] = [None] * len(deva)
    for a, b in runs:
        best, best_ov = -1, 0.0
        for i, bb in enumerate(deva):
            ov = min(b, bb.y1) - max(a, bb.y0)
            if ov > best_ov:
                best, best_ov = i, ov
        if best >= 0:
            cur = ink[best]
            ink[best] = (a, b) if cur is None else (min(cur[0], a), max(cur[1], b))
    if any(x is None for x in ink):
        return _metric_midpoints()
    # neighbouring lines must be separated by real whitespace to cut cleanly
    if any(ink[i][1] >= ink[i + 1][0] for i in range(len(ink) - 1)):
        return _metric_midpoints()

    out = []
    for i, (a, b) in enumerate(ink):
        top = (ink[i - 1][1] + a) / 2 if i else a - CLIP_EDGE_PAD
        bot = (b + ink[i + 1][0]) / 2 if i < len(ink) - 1 else b + CLIP_EDGE_PAD
        out.append(fitz.Rect(deva[i].x0, top, deva[i].x1, bot))
    return out


def _pair_body(deva, tl):
    """One-line-per-pada first; else merge wrapped continuation lines."""
    if not deva or not tl:
        return None
    return _rows_for(deva, [[t] for t in tl]) or _rows_for(deva, _group_padas(tl))


def verse_rows(deva, tl, attrib=0):
    """Ordered rows for the interleaved verse, or None if not cleanly pairable.

    A row is a list of ("clip", bbox, scale) / ("sep",) segments on one baseline.
    `attrib` leading speaker-attribution lines (e.g. "vyäsa uväca") are peeled off
    and paired 1:1, then the verse body is paired on its own — so a 3-vs-5 verse
    (attribution + a 2-vs-4 body) interleaves cleanly.
    """
    if not deva or not tl:
        return None
    attrib = min(attrib, len(deva) - 1, len(tl) - 1)   # keep at least a body line
    if attrib > 0:
        body = _pair_body(deva[attrib:], tl[attrib:])
        if body is not None:
            head = []
            for i in range(attrib):
                head.append([("clip", tl[i], TL_SCALE)])       # attribution: translit
                head.append([("clip", deva[i], DEVA_SCALE)])   # then its Devanagari
            return head + body
    return _pair_body(deva, tl)


def is_transformable(src, pno):
    deva, tl, tl_texts, _ = classify_lines(src[pno])
    return verse_rows(deva, tl, leading_attributions(tl_texts)) is not None


def _render_row(new, src, pno, row, y, max_w):
    clips = [seg for seg in row if seg[0] == "clip"]
    n_sep = sum(1 for seg in row if seg[0] == "sep")
    n_gap = sum(1 for seg in row if seg[0] == "gap")
    base_sz = 17 * TL_SCALE
    sep_w = fitz.get_text_length(SEP, fontname=SEP_FONT, fontsize=base_sz)
    nat_w = sum(bb.width * sc for _, bb, sc in clips) + sep_w * n_sep + DEVA_GAP * n_gap
    fit = min(1.0, max_w / nat_w) if nat_w > max_w else 1.0
    row_h = max(bb.height * sc for _, bb, sc in clips) * fit

    x = (new.rect.width - nat_w * fit) / 2
    for seg in row:
        if seg[0] == "sep":
            new.insert_text((x, y + row_h * 0.72), SEP, fontname=SEP_FONT,
                            fontsize=base_sz * fit, color=SEP_COLOR)
            x += sep_w * fit
        elif seg[0] == "gap":                       # blank space between clubbed padas
            x += DEVA_GAP * fit
        else:
            _, bb, sc = seg
            w, h = bb.width * sc * fit, bb.height * sc * fit
            new.show_pdf_page(fitz.Rect(x, y, x + w, y + h), src, pno, clip=bb)
            x += w
    return row_h


def _compose(new, src, pno, rows, deva, tl, side_margin=SIDE_MARGIN):
    """Stamp header + given rows + the word-for-word/translation block onto page
    `new`, copying vector content from src[pno]. `deva`/`tl` set the verse bounds."""
    page = src[pno]
    W, H = page.rect.width, page.rect.height
    verse_top = min(r.y0 for r in deva + tl)
    verse_bot = max(r.y1 for r in deva + tl)

    below = [sp["bbox"] for b in page.get_text("dict")["blocks"]
             for ln in b.get("lines", []) for sp in ln["spans"]
             if sp["text"].strip() and sp["bbox"][1] > verse_bot + 1 and sp["bbox"][3] < H - 30]

    new.show_pdf_page(fitz.Rect(0, 0, W, verse_top), src, pno,
                      clip=fitz.Rect(0, 0, W, verse_top))            # header

    max_w = W - 2 * side_margin
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


def draw_interleaved(new, src, pno):
    """Interleaved page: each transliteration pada above its enlarged Devanagari.
    Returns False if the verse isn't cleanly pairable."""
    page = src[pno]
    deva, tl, tl_texts, is_rm = classify_lines(page)
    if is_rm:                                     # RM Devanagari clips descenders;
        deva = expand_deva(page, deva)            # Indevr is fine, leave it tight
    rows = verse_rows(deva, tl, leading_attributions(tl_texts))
    if rows is None:
        return False
    return _compose(new, src, pno, rows, deva, tl)


def draw_enlarged_sloka(new, src, pno):
    """Fallback for verses that can't be interleaved: the whole Devanagari block
    enlarged 1.5x, then the transliteration block — same order as the original
    sloka page. Returns False if there's no Devanagari to enlarge (CC/CB)."""
    page = src[pno]
    deva, tl, _, is_rm = classify_lines(page)
    if not deva:
        return False
    if is_rm:
        deva = expand_deva(page, deva)
    rows = [[("clip", d, DEVA_SCALE)] for d in deva] \
        + [[("clip", t, TL_SCALE)] for t in tl]
    return _compose(new, src, pno, rows, deva, tl)


# --------------------------------------------------------------------------
# Clubbed layout — two padas per line (the traditional couplet layout)
# --------------------------------------------------------------------------
# The interleaved page draws one pada per line, enlarging the Devanagari 1.5x.
# When the source prints one pada per Devanagari line (canto 10-12 mostly), the
# verse can instead be *clubbed* into couplets: two padas side by side per line,
# like the older cantos that pack 2/line. This is more compact but shrinks the
# Devanagari (two padas rarely fit the page at 1.5x, so the row auto-fits down).
# Clubbable verses get this as their primary enhanced page, keeping the enlarged
# 1-pada/line page as a second "read large" page right after it.


def _clubbable_body(deva, tl, attrib):
    """True when the verse body is a clean 1:1 pairing (one pada per Devanagari
    line) with at least one couplet's worth of padas to club."""
    if not deva or not tl:
        return False
    attrib = min(attrib, len(deva) - 1, len(tl) - 1)
    db, tb = deva[attrib:], tl[attrib:]
    return len(db) == len(tb) and len(db) >= 2


def is_clubbable(src, pno):
    """A transformable verse whose Devanagari is one-pada-per-line — the only
    kind the clubbed couplet layout applies to."""
    deva, tl, tl_texts, _ = classify_lines(src[pno])
    attrib = leading_attributions(tl_texts)
    if verse_rows(deva, tl, attrib) is None:
        return False
    return _clubbable_body(deva, tl, attrib)


def _clubbed_rows(deva, tl, attrib):
    """Rows with two padas per line. Leading attribution lines stay paired 1:1;
    the body pairs consecutive padas side by side (a lone trailing pada stays on
    its own line)."""
    attrib = min(attrib, len(deva) - 1, len(tl) - 1)
    rows = []
    for i in range(attrib):                              # attribution: 1:1 stacked
        rows.append([("clip", tl[i], TL_SCALE)])
        rows.append([("clip", deva[i], DEVA_SCALE)])
    db, tb = deva[attrib:], tl[attrib:]
    i, n = 0, len(db)
    while i < n:
        if i + 1 < n:                                    # a couplet, side by side
            rows.append([("clip", tb[i], TL_SCALE), ("sep",), ("clip", tb[i + 1], TL_SCALE)])
            rows.append([("clip", db[i], DEVA_SCALE), ("gap",), ("clip", db[i + 1], DEVA_SCALE)])
            i += 2
        else:                                            # lone trailing pada
            rows.append([("clip", tb[i], TL_SCALE)])
            rows.append([("clip", db[i], DEVA_SCALE)])
            i += 1
    return rows


def draw_clubbed(new, src, pno):
    """Clubbed page: two padas per line. Returns False if the verse isn't a clean
    one-pada-per-line verse (nothing to club)."""
    page = src[pno]
    deva, tl, tl_texts, is_rm = classify_lines(page)
    attrib = leading_attributions(tl_texts)
    if verse_rows(deva, tl, attrib) is None or not _clubbable_body(deva, tl, attrib):
        return False
    if is_rm:
        deva = expand_deva(page, deva)
    rows = _clubbed_rows(deva, tl, attrib)
    return _compose(new, src, pno, rows, deva, tl, side_margin=CLUB_MARGIN)
