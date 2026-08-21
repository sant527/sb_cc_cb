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
import unicodedata

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
STRETCH_MARGIN = 14  # side margin for the full-width stretched reading page
STRETCH_GAP = 22     # gap between padas on a 2-per-row stretched page

# Glossed page: printed word-for-word placed above each Devanagari word.
GLOSS_REG = "/System/Library/Fonts/Supplemental/Times New Roman.ttf"
GLOSS_ITA = "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf"
GLOSS_SIZE = 12.5
GLOSS_A = (0.48, 0.13, 0.62)      # purple — alternates per word (meaning + underline)
GLOSS_B = (0.06, 0.46, 0.48)      # teal
GLOSS_TRANS = (0.55, 0.55, 0.55)  # subtle grey for the transliteration line

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


# --------------------------------------------------------------------------
# Stretched reading page — Devanagari scaled to fill the page width
# --------------------------------------------------------------------------
# A big, clean reading page: every Devanagari line is scaled by one uniform
# factor so the widest line runs edge to edge, and the trailing dandas / verse
# number ("… ॥ 24 ॥") are dropped so they don't cap the width. `per_row` lays the
# lines out one pada per row (per_row=1, biggest) or two per row (per_row=2, the
# couplet look). No clubbing / pairing analysis — it just groups the lines.


def _strip_danda(page, line):
    """Clip a Devanagari line to drop a trailing danda run — a single ')' (।) or
    the ')) N ))' of a verse number (॥ N ॥) in this legacy encoding. '(' is a
    virama (real content) and is kept."""
    chars = []
    for b in page.get_text("rawdict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln.get("spans", []):
                for ch in sp.get("chars", []):
                    x0, y0, x1, y1 = ch["bbox"]
                    if y0 >= line.y0 - 2 and y1 <= line.y1 + 2:
                        chars.append((x0, x1, ch["c"]))
    chars.sort()
    i = len(chars) - 1
    while i >= 0 and (chars[i][2].strip() == "" or chars[i][2] == ")" or chars[i][2].isdigit()):
        i -= 1
    return line if i < 0 else fitz.Rect(line.x0, line.y0, chars[i][1], line.y1)


def draw_stretched(new, src, pno, per_row=1, translit=True):
    """Full-width stretched reading page. `per_row` Devanagari lines per row
    (1 = one pada/row, 2 = couplets). `translit=False` drops the roman sloka,
    leaving Devanagari + word-for-word + translation. False if no Devanagari."""
    page = src[pno]
    deva, tl, tt, is_rm = classify_lines(page)
    if not deva:
        return False
    W, H = page.rect.width, page.rect.height
    attrib = leading_attributions(tt)

    xclips = [_strip_danda(page, b) for b in deva]           # trim trailing dandas (x)
    ys = expand_deva(page, deva) if is_rm else deva          # recover descenders (y)
    clips = [fitz.Rect(xclips[i].x0, ys[i].y0, xclips[i].x1, ys[i].y1)
             for i in range(len(deva))]

    # rows: each attribution line on its own, then the body `per_row` at a time
    groups = [[clips[i]] for i in range(attrib)]
    body = clips[attrib:]
    for i in range(0, len(body), per_row):
        groups.append(body[i:i + per_row])

    def gw(g):
        return sum(c.width for c in g) + STRETCH_GAP * (len(g) - 1)

    max_w = W - 2 * STRETCH_MARGIN
    sc = max_w / max(gw(g) for g in groups)                  # one factor, widest row fills

    verse_top = min(r.y0 for r in deva + tl)
    verse_bot = max(r.y1 for r in deva + tl)
    below = [sp["bbox"] for b in page.get_text("dict")["blocks"]
             for ln in b.get("lines", []) for sp in ln["spans"]
             if sp["text"].strip() and sp["bbox"][1] > verse_bot + 1 and sp["bbox"][3] < H - 30]

    new.show_pdf_page(fitz.Rect(0, 0, W, verse_top), src, pno,
                      clip=fitz.Rect(0, 0, W, verse_top))     # header
    y = verse_top
    for g in groups:
        h = max(c.height for c in g) * sc
        x = (W - gw(g) * sc) / 2
        for j, c in enumerate(g):
            if j:
                x += STRETCH_GAP * sc
            w = c.width * sc
            new.show_pdf_page(fitz.Rect(x, y, x + w, y + c.height * sc), src, pno, clip=c)
            x += w
        y += h + VERSE_GAP
    if translit:                                            # roman sloka (skipped for no-roman)
        y += BELOW_GAP
        for t in tl:
            w, h = t.width * TL_SCALE, t.height * TL_SCALE
            new.show_pdf_page(fitz.Rect((W - w) / 2, y, (W - w) / 2 + w, y + h), src, pno, clip=t)
            y += h + 2
    if below:
        top = min(r[1] for r in below) - 2
        bot = max(r[3] for r in below) + 2
        y += BELOW_GAP
        new.show_pdf_page(fitz.Rect(0, y, W, y + (bot - top)), src, pno, clip=fitz.Rect(0, top, W, bot))
    return True


# --------------------------------------------------------------------------
# Glossed page — the printed word-for-word placed above each Devanagari word
# --------------------------------------------------------------------------
# Only the meanings already printed below the sloka are used (never invented).
# Each word's roman transliteration + English meaning is aligned to a position
# in its pada (approximate — the Devanagari is sandhi-joined) and drawn above the
# full-width Devanagari, with a dark underline marking each word's span.


def _parse_wff(text):
    """(word, meaning) pairs from word-for-word text: split on ';' then the em-dash.
    Don't cut at the first period — a meaning may contain one ('…Nakula and
    Sahadeva).') and combined verses run several sentences."""
    out = []
    for part in text.split(";"):
        if "—" in part:
            w, m = part.split("—", 1)
            w, m = w.strip(), m.strip().rstrip(".").strip()
            if w and m:
                out.append((w, m))
    return out


def _word_for_word(page):
    """(word, meaning) pairs from the whole page's em-dash lines (used as a cheap
    'is there a word-for-word block?' probe; draw_glossed parses the precise region
    itself so wrapped meanings are kept)."""
    lines = [ln for ln in page.get_text().split("\n") if "—" in ln]
    return _parse_wff(" ".join(lines)) if lines else []


def _gloss_norm(s, readable):
    s = unicodedata.normalize("NFKD", readable(s))
    return "".join(c for c in s if c.isalpha() and not unicodedata.combining(c)).lower()


def _align_glosses(entries, tt, ndeva, readable):
    """place[deva_line] = [(frac, translit, meaning), …]. A leading attribution
    line (… uvāca) is peeled off first (one pada, one line); the body's padas then
    divide evenly across the remaining lines, k per line, and a word's x-fraction
    is (slot + within-pada)/k (so two-padas/line verses map left half / right half).
    None when the body padas don't divide evenly (an irregular verse)."""
    if not tt or ndeva == 0:
        return None
    a = min(leading_attributions(tt), ndeva - 1, len(tt) - 1)   # attribution lines peeled off
    a = max(a, 0)
    body_deva, body_tt = ndeva - a, len(tt) - a
    if body_deva <= 0 or body_tt <= 0 or body_tt % body_deva != 0:
        return None
    bk = body_tt // body_deva

    def pada_line(pi):                               # pada index -> (deva line, slot, k of line)
        if pi < a:
            return pi, 0, 1
        b = pi - a
        return a + b // bk, b % bk, bk

    padas = [_gloss_norm(t, readable) for t in tt]
    bounds, glob = [], ""
    for i, pn in enumerate(padas):
        bounds.append((len(glob), len(glob) + len(pn), i, len(pn)))
        glob += pn
    total = len(glob)
    words = [(w, mn, _gloss_norm(w, readable)) for w, mn in entries]
    words = [x for x in words if x[2]]
    n = len(words)
    if n == 0 or total == 0:
        return None

    # ANCHOR: match the words that survive sandhi (in order), recording their real
    # char position. cursor only moves forward, so anchors stay monotonic.
    pos = [None] * n
    cursor = anchors = 0
    for i, (w, mn, wn) in enumerate(words):
        idx, ml = glob.find(wn, cursor), len(wn)
        if idx < 0:
            for kk in range(len(wn) - 1, 3, -1):     # longest prefix that still matches
                idx = glob.find(wn[:kk], cursor)
                if idx >= 0:
                    ml = kk
                    break
        if idx >= 0:
            pos[i], cursor, anchors = idx, idx + max(1, ml), anchors + 1
    if anchors == 0:                                 # nothing matched -> can't align
        return None

    # INTERPOLATE the sandhi-missed words: they sit between their matched neighbours,
    # spaced by word length. Sentinels pin the ends of the verse.
    weight = [max(1, len(wn)) for _, _, wn in words]
    cumw, acc = [], 0
    for wt in weight:
        cumw.append(acc)
        acc += wt
    ax = [0.0] + [cumw[i] for i in range(n) if pos[i] is not None] + [float(acc)]
    ay = [0.0] + [float(pos[i]) for i in range(n) if pos[i] is not None] + [float(total)]

    def interp(cw):
        for j in range(1, len(ax)):
            if cw <= ax[j]:
                x0, x1, y0, y1 = ax[j - 1], ax[j], ay[j - 1], ay[j]
                return y0 if x1 == x0 else y0 + (y1 - y0) * (cw - x0) / (x1 - x0)
        return ay[-1]

    place = [[] for _ in range(ndeva)]
    for i, (w, mn, wn) in enumerate(words):
        p = pos[i] if pos[i] is not None else interp(cumw[i])
        for gs, ge, pi, pl in bounds:
            if gs <= p < ge:
                line, slot, klen = pada_line(pi)
                frac = (slot + min(max((p - gs) / pl, 0.0), 1.0)) / klen
                place[line].append((frac, readable(w).replace(" ", ""), readable(mn)))
                break
    return place


def _gloss_degenerate(place):
    """True when a placement is visibly wrong — the signature of a word-for-word
    printed in anvaya (grammatical) rather than verse-line order, which the
    forward-cursor aligner squashes. Two tells:
      (a) a Devanagari line got no gloss while another hogs ≥75% of them, and
      (b) x-piling: a majority of one line's glosses collapse into a narrow band
          (interpolated words stranded past the last anchor pile at one x)."""
    if place is None:
        return True
    counts = [len(x) for x in place]
    total = sum(counts)
    if total == 0:
        return True
    if len(place) >= 2 and sum(1 for c in counts if c) < len(place) and total >= len(place):
        if max(counts) / total >= 0.75:
            return True
    for line in place:                            # (b) narrow-band pile-up on any line
        k = len(line)
        if k >= 4:
            fr = sorted(f for f, _, _ in line)
            j = best = 0
            for i in range(k):
                while fr[i] - fr[j] > 0.2:         # widest run inside a 0.2 frac window
                    j += 1
                best = max(best, i - j + 1)
            if best >= 4 and best >= 0.6 * k:
                return True
    return False


def _line_balance(place):
    """Ratio of the least-filled to most-filled Devanagari line (1.0 = even). A very
    low value means the aligner piled most glosses onto one line while starving
    another — a milder pile the frac-window test can miss (SB 9.24.32: [1, 11])."""
    c = [len(x) for x in place]
    return min(c) / max(c) if c and max(c) else 1.0


def _sandhi_forms(wn):
    """Common sandhi variants of a headword as it may appear fused in the sloka: a
    leading vowel elided (avagraha), and a final visarga transformed — aḥ → o
    (saḥ → so, kālaḥ → kālo), ḥ → r/s, or dropped — plus a dropped final anusvara.
    Excludes the base form itself (handled by the exact pass)."""
    forms = set()
    bases = [wn] + ([wn[1:]] if wn[:1] in "aiueo" else [])
    for b in bases:
        if not b:
            continue
        forms.add(b)
        if b.endswith("ah"):
            forms.update((b[:-2] + "o", b[:-2] + "ar", b[:-1] + "r", b[:-1]))
        elif b.endswith("h"):
            forms.update((b[:-1] + "r", b[:-1] + "s", b[:-1]))
        if b.endswith("m"):
            forms.add(b[:-1])
    forms.discard(wn)
    forms.discard("")
    return forms


def _edit_le1(a, b):
    """True when strings a and b are within Levenshtein distance 1 (one
    substitution, insertion, or deletion) — enough to bridge a single sandhi
    character between a word-for-word headword and the sloka."""
    la, lb = len(a), len(b)
    if la == lb:
        return sum(x != y for x, y in zip(a, b)) <= 1
    if abs(la - lb) != 1:
        return False
    if la > lb:                                   # make a the shorter
        a, b, la, lb = b, a, lb, la
    i = j = 0
    skipped = False
    while i < la and j < lb:                      # is a b with one char deleted?
        if a[i] == b[j]:
            i += 1; j += 1
        elif skipped:
            return False
        else:
            skipped = True; j += 1
    return True


def _align_glosses_oi(entries, tt, ndeva, readable):
    """Order-independent aligner for anvaya-ordered word-for-word blocks. Each
    headword finds its own position in the sloka (all occurrences, verbatim then
    longest-prefix ≥4 for sandhi), and matches are assigned greedily by confidence
    with claimed spans so repeated particles don't collide. Words that survive no
    match (fully sandhi-hidden) are dropped rather than guessed — better a correct
    partial gloss than a scrambled full one. Same pada/line geometry as the primary
    aligner; None when the padas don't divide evenly or nothing matched."""
    if not tt or ndeva == 0:
        return None
    a = max(min(leading_attributions(tt), ndeva - 1, len(tt) - 1), 0)
    body_deva, body_tt = ndeva - a, len(tt) - a
    if body_deva <= 0 or body_tt <= 0 or body_tt % body_deva != 0:
        return None
    bk = body_tt // body_deva

    def pada_line(pi):
        if pi < a:
            return pi, 0, 1
        b = pi - a
        return a + b // bk, b % bk, bk

    padas = [_gloss_norm(t, readable) for t in tt]
    bounds, glob = [], ""
    for i, pn in enumerate(padas):
        bounds.append((len(glob), len(glob) + len(pn), i, len(pn)))
        glob += pn
    total = len(glob)
    words = [(w, mn, _gloss_norm(w, readable)) for w, mn in entries]
    words = [x for x in words if x[2]]
    n = len(words)
    if n == 0 or total == 0:
        return None

    def occ(key):                                # all verbatim start positions of key
        out, st = [], glob.find(key)
        while st >= 0:
            out.append(st)
            st = glob.find(key, st + 1)
        return out

    cands = []                                   # (confidence, word-index, pos, match-len)
    for i, (w, mn, wn) in enumerate(words):
        starts = [(len(wn), p, len(wn)) for p in occ(wn)]     # verbatim
        if not starts and wn[:1] in "aiueo" and len(wn) > 4:  # leading vowel elided (avagraha, e.g. aśayiṣṭa -> 'śayiṣṭa)
            tail = wn[1:]
            starts = [(len(tail), p, len(tail)) for p in occ(tail)]
        if not starts and len(wn) > 4:                        # trailing sandhi: longest prefix
            for kk in range(len(wn) - 1, 3, -1):
                ps = occ(wn[:kk])
                if ps:
                    starts = [(kk, p, kk) for p in ps]
                    break
        cands += [(conf, i, pos, ml) for conf, pos, ml in starts]
    cands.sort(reverse=True)                      # most-confident matches claim first
    posn, claimed = [None] * n, []

    def overlaps(s, e):                          # tolerate a 1-char shared vowel: adjacent
        return any(min(e, ce) - max(s, cs) >= 2   # words fuse at the sandhi boundary (ā+a→ā)
                   for cs, ce in claimed)

    for conf, i, pos, ml in cands:
        if posn[i] is not None or overlaps(pos, pos + ml):
            continue
        posn[i] = pos
        claimed.append((pos, pos + ml))

    # second pass: a word still unplaced has been sandhi-fused into the sloka — a
    # final visarga changed (saḥ → so, kālaḥ → kālo, anantaḥ → 'nanto), a leading
    # vowel elided, a coalesced vowel (sa-anubandhasya → sānubandhasya) — or its only
    # exact hit was inside a longer word already claimed (yat inside man·yat·e). Try
    # its sandhi variants exactly, then a 1-edit fuzzy match, and take the leftmost
    # unclaimed span.
    for i, (w, mn, wn) in enumerate(words):
        if posn[i] is not None or len(wn) < 2:
            continue
        spans = []
        for form in _sandhi_forms(wn):                    # exact sandhi variants
            if len(form) >= 2:
                spans += [(p, len(form)) for p in occ(form)]
        if len(wn) >= 4:                                  # 1-edit fuzzy of the base word
            for L in (len(wn), len(wn) - 1, len(wn) + 1):
                spans += [(p, L) for p in range(len(glob) - L + 1)
                          if _edit_le1(wn, glob[p:p + L])]
        for p, L in sorted(spans):                        # leftmost unclaimed wins
            if not overlaps(p, p + L):
                posn[i] = p
                claimed.append((p, p + L))
                break

    if not any(p is not None for p in posn):
        return None

    place = [[] for _ in range(ndeva)]
    for i, (w, mn, wn) in enumerate(words):
        p = posn[i]
        if p is None:                             # unlocatable -> skip, don't guess
            continue
        for gs, ge, pi, pl in bounds:
            if gs <= p < ge:
                line, slot, klen = pada_line(pi)
                frac = (slot + min(max((p - gs) / pl, 0.0), 1.0)) / klen
                place[line].append((frac, readable(w).replace(" ", ""), readable(mn)))
                break
    return place


def draw_glossed(new, src, pno):
    """Glossed reading page — full-width Devanagari (one pada per row) with each
    printed word-for-word gloss above its word. False when the verse has no
    parseable word-for-word or its padas don't divide evenly into the Devanagari
    lines (an irregular verse that can't be word-aligned)."""
    from reader import readable                       # lazy: only the build imports reader
    page = src[pno]
    deva, tl, tt, is_rm = classify_lines(page)
    if not deva or not tt:
        return False
    # fold a wrapped continuation (a short trailing line, e.g. a lone 'dhīmahi'
    # off a long-metre pada) back into its pada, so the pada count matches the
    # Devanagari — this rescues verses like SB 1.1.1
    if tl:
        full = max(b.width for b in tl)
        merged = []
        for t, b in zip(tt, tl):
            if merged and b.width < WRAP_MAX_FRAC * full:
                merged[-1] += " " + t
            else:
                merged.append(t)
        tt = merged
    W, H = page.rect.width, page.rect.height
    xclips = [_strip_danda(page, b) for b in deva]
    ys = expand_deva(page, deva) if is_rm else deva
    clips = [fitz.Rect(xclips[i].x0, ys[i].y0, xclips[i].x1, ys[i].y1) for i in range(len(deva))]
    sc = (W - 2 * STRETCH_MARGIN) / max(c.width for c in clips)
    verse_top = min(r.y0 for r in deva + tl)
    verse_bot = max(r.y1 for r in deva + tl)
    # split what's below the sloka into the word-for-word block and the translation.
    # Text-only signals (paragraph gap, em-dash, semicolons) all fail on some verse:
    # the gap is sometimes absent (SB 8.11.23), translations can contain em-dashes
    # (SB 1.11.11) and semicolons (SB 5.23.7), and the last word-for-word meaning can
    # wrap onto plain roman lines (SB 1.7.12). The reliable mark is the FONT:
    # word-for-word terms are italic transliteration, the translation is roman prose
    # opening with a capital — the first full-width, near-all-roman line.
    below_all = [(sp["bbox"], sp["text"], bool(sp["flags"] & 2))
                 for b in page.get_text("dict")["blocks"]
                 for ln in b.get("lines", []) for sp in ln["spans"]
                 if sp["text"].strip() and sp["bbox"][1] > verse_bot + 1 and sp["bbox"][3] < H - 30]
    lines = []                            # [y0, text, x0, x1, italic_chars, total_chars]
    for bb, t, it in sorted(below_all, key=lambda s: (round(s[0][1]), s[0][0])):
        if lines and abs(bb[1] - lines[-1][0]) <= 3:
            L = lines[-1]
            L[1] += t; L[2] = min(L[2], bb[0]); L[3] = max(L[3], bb[2])
            L[4] += len(t) if it else 0; L[5] += len(t)
        else:
            lines.append([bb[1], t, bb[0], bb[2], len(t) if it else 0, len(t)])
    translation_top = H
    for y0, t, x0, x1, ic, tc in lines:
        first = next((c for c in t if c.isalpha()), "")
        if first.isupper() and (x1 - x0) > 0.45 * W and ic / max(1, tc) < 0.15:
            translation_top = y0
            break
    below = [bb for bb, t, it in below_all if bb[1] >= translation_top - 2]

    # parse the word-for-word from the region between the sloka and the translation,
    # in reading order — so a meaning that wraps onto the next line ("āvaliḥ — a /
    # mass.") is kept whole and translation em-dashes are excluded
    wff_text = page.get_text(clip=fitz.Rect(0, verse_bot + 1, W, translation_top - 1))
    entries = _parse_wff(wff_text.replace("\n", " "))
    if not entries:
        return False
    place = _align_glosses(entries, tt, len(deva), readable)
    if place is None:                                # irregular pada/line structure
        return False
    if _gloss_degenerate(place):                     # anvaya-ordered word-for-word:
        place = _align_glosses_oi(entries, tt, len(deva), readable)   # retry order-free
        if _gloss_degenerate(place):                 # still wrong -> repeat stretched page
            return False
    elif _line_balance(place) < 0.35:                # not flagged but lopsided (piled onto
        oi = _align_glosses_oi(entries, tt, len(deva), readable)   # one line) — prefer the
        if oi is not None and not _gloss_degenerate(oi) and _line_balance(oi) >= 0.6:  # order-free
            place = oi                               # result when it spreads far more evenly

    freg, fita = fitz.Font(fontfile=GLOSS_REG), fitz.Font(fontfile=GLOSS_ITA)
    GS, LH = GLOSS_SIZE, GLOSS_SIZE + 1.5

    # lay out each line's glosses (positions + stagger level) up front, so a line
    # reserves only the vertical space its own glosses need — no wasted gap.
    layouts = []
    for i, c in enumerate(clips):
        w = c.width * sc
        x0 = (W - w) / 2
        pl = sorted(place[i]) if i < len(place) else []
        items, row_end, maxlvl = [], [], 0     # row_end[l] = right edge used at stagger level l
        for j, (frac, word, mn) in enumerate(pl):
            gx = x0 + frac * w
            xb = x0 + (pl[j + 1][0] if j + 1 < len(pl) else 1.0) * w
            gw = max(fita.text_length(word, GS), freg.text_length(mn, GS))
            lvl = 0                            # lowest row where this gloss doesn't collide
            while lvl < len(row_end) and gx < row_end[lvl] + 5:
                lvl += 1
            if lvl == len(row_end):
                row_end.append(0.0)
            row_end[lvl] = gx + gw
            items.append((gx, xb, word, mn, lvl))
            maxlvl = max(maxlvl, lvl)
        layouts.append((c, x0, w, c.height * sc, items, maxlvl))

    tl_top = tl_bot = None
    if below:
        tl_top = min(r[1] for r in below) - 2
        tl_bot = max(r[3] for r in below) + 2

    # the printed word-for-word block (the source region above the translation) is
    # reproduced verbatim at the very bottom, after the translation, for reference
    wff_spans = [bb for bb, t, it in below_all if bb[1] < translation_top - 2]
    wf_top = wf_bot = None
    if wff_spans:
        wf_top = min(r[1] for r in wff_spans) - 2
        wf_bot = max(r[3] for r in wff_spans) + 2

    # a crowded verse (deep gloss stacks) can push the translation past the source
    # page height and clip it — grow the page to exactly the height the content
    # needs, so nothing is ever cut off the bottom.
    needed = verse_top
    for c, x0, w, h, items, maxlvl in layouts:
        needed += (2 + 2 * maxlvl) * LH + 4 + h + VERSE_GAP
    if below:
        needed += BELOW_GAP + (tl_bot - tl_top)
    if wf_top is not None:
        needed += 10 + (wf_bot - wf_top)             # 10pt before the reference block
    needed += 80                                     # trailing whitespace (room to scroll)
    if needed > H:
        new.set_mediabox(fitz.Rect(0, 0, W, needed))   # before any content is placed
        H = needed

    new.insert_font(fontname="GR", fontfile=GLOSS_REG)
    new.insert_font(fontname="GI", fontfile=GLOSS_ITA)

    new.show_pdf_page(fitz.Rect(0, 0, W, verse_top), src, pno, clip=fitz.Rect(0, 0, W, verse_top))
    gi = 0
    y = verse_top
    for c, x0, w, h, items, maxlvl in layouts:
        y += (2 + 2 * maxlvl) * LH + 4               # just enough for translit + meaning
        new.show_pdf_page(fitz.Rect(x0, y, x0 + w, y + h), src, pno, clip=c)
        base = y - 6
        for gx, xb, word, mn, lvl in items:
            col = GLOSS_A if gi % 2 == 0 else GLOSS_B     # meaning + underline alternate
            gi += 1
            yb = base - lvl * 2 * LH
            new.insert_text((gx, yb - LH), word, fontname="GI", fontsize=GS, color=GLOSS_TRANS)
            new.insert_text((gx, yb), mn, fontname="GR", fontsize=GS, color=col)
            new.draw_line((gx + 2, y + h + 2), (xb - 2, y + h + 2), color=col, width=2.6)
        y += h + VERSE_GAP
    if below:
        y += BELOW_GAP
        new.show_pdf_page(fitz.Rect(0, y, W, y + (tl_bot - tl_top)), src, pno, clip=fitz.Rect(0, tl_top, W, tl_bot))
        y += tl_bot - tl_top
    if wf_top is not None:                            # word-for-word reference block
        y += 10                                       # 10pt below the translation
        new.show_pdf_page(fitz.Rect(0, y, W, y + (wf_bot - wf_top)), src, pno, clip=fitz.Rect(0, wf_top, W, wf_bot))
    return True
