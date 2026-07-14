"""
SB/CC/CB Reader — a MuPDF-backed navigator for SB_CC_CB_ALL_NEW_INDEX_Oct3_2021.pdf

Navigation model:
    RIGHT tap        -> NEXT translation
    RIGHT long-press -> NEXT page (repeats while held)
    LEFT  tap        -> PREV translation
    LEFT  long-press -> PREV page (repeats while held)

A "translation" is a level-4 outline entry (e.g. "--- SB 1.1.1 / 23",
"Madhya 20.268 / 406", "CBAdi 10.112 / 131"); each lands on the page holding
that verse's English translation. There are ~36,000 of them across 237,298 pages.
"""

from __future__ import annotations

import bisect
import json
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz
import numpy as np
from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QImage, QKeyEvent, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

PDF_NAME = "SB_CC_CB_ALL_NEW_INDEX_Oct3_2021.pdf"

ZOOM_MIN, ZOOM_MAX = 0.4, 6.0


# --------------------------------------------------------------------------
# Colour ladder  (UP = dimmer, rolls into the next theme; DOWN = reverse; wraps)
# --------------------------------------------------------------------------

RGB = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class Theme:
    name: str
    ink: RGB      # what pure black in the page becomes
    paper: RGB    # what pure white in the page becomes


BLACK, WHITE = (0, 0, 0), (255, 255, 255)

THEMES = (
    Theme("Normal",     BLACK, WHITE),                      # white page, black letters
    Theme("Inverted",   WHITE, BLACK),                      # dark page, white letters
    Theme("Green",      BLACK, (186, 224, 176)),            # green page, black letters
    Theme("Orange",     BLACK, (250, 206, 148)),            # orange page, black letters
    Theme("Solarized",  (101, 123, 131), (253, 246, 227)),  # base00 on base3
    Theme("Solar Dark", (131, 148, 150), (0, 43, 54)),      # base0  on base03
    Theme("Monokai",    (248, 248, 242), (39, 40, 34)),     # Sublime Text's classic default
    Theme("Mariana",    (216, 222, 233), (52, 61, 70)),     # Sublime Text's newer default
    Theme("Sepia",      BLACK, (244, 236, 216)),            # warm paper
)

# 8 brightness variations per theme: brightest -> shaded.
DIM_LEVELS = (1.00, 0.91, 0.83, 0.74, 0.66, 0.57, 0.49, 0.40)


def build_lut(theme: Theme, dim: float) -> "np.ndarray":
    """Per-channel 256-entry lookup: source pixel -> themed, dimmed pixel.

    Each channel ramps independently from `ink` (source 0) to `paper` (source
    255). Applying it per channel rather than off a single luminance keeps the
    page's own colour: with a black ink this is exactly a multiply by the paper,
    so the gold headings tint along instead of flattening to grey.
    """
    t = np.arange(256, dtype=np.float64) / 255.0
    lut = np.empty((3, 256), dtype=np.uint8)
    for ch in range(3):
        ramp = theme.ink[ch] + (theme.paper[ch] - theme.ink[ch]) * t
        lut[ch] = np.clip(np.rint(ramp * dim), 0, 255).astype(np.uint8)  # rint: uint8 cast truncates
    return lut


# --------------------------------------------------------------------------
# Index
# --------------------------------------------------------------------------

# The outline's chapter titles are double-smeared: each UTF-8 byte was pushed
# into the halfwidth/fullwidth block (byte b -> U+FF00+b), twice. Undoing that
# lands on the PDF's legacy Balaram transliteration font, which the embedded
# font renders correctly on the page but which extracts as "Çré Kåñëa".
BALARAM = str.maketrans({
    "ä": "ā", "Ä": "Ā", "é": "ī", "É": "Ī", "ü": "ū", "Ü": "Ū",
    "å": "ṛ", "Å": "Ṛ", "ë": "ṇ", "Ë": "Ṇ", "ï": "ñ", "Ï": "Ñ",
    "ñ": "ṣ", "Ñ": "Ṣ", "ç": "ś", "Ç": "Ś", "ö": "ṭ", "Ö": "Ṭ",
    "ò": "ḍ", "Ò": "Ḍ", "ù": "ḥ", "Ù": "Ḥ", "à": "ṁ", "À": "Ṁ",
})


def _unsmear(s: str) -> str:
    """Undo one layer of the byte -> U+FF00+b smear."""
    if not any(0xFF00 <= ord(c) <= 0xFFFF for c in s):
        return s
    buf = bytearray()
    for c in s:
        o = ord(c)
        buf.extend(bytes([o - 0xFF00]) if 0xFF00 <= o <= 0xFFFF else c.encode())
    return buf.decode("utf-8", errors="replace")


def readable(title: str) -> str:
    """Outline title -> something a human can read in the status bar."""
    return _unsmear(_unsmear(title)).translate(BALARAM)


@dataclass(slots=True)
class Translation:
    page: int      # 1-based; the English translation
    label: str     # "SB 1.1.1 / 23"
    chapter: str   # "SB 1.1: Questions by the Sages"
    sloka: int     # the verse itself

    @staticmethod
    def sloka_page(label: str, page: int) -> int:
        """Where the verse text sits, relative to the translation.

        SB lays the sloka on the page *after* the translation (the 8,321 verses
        with a PURPORT have it at exactly +2, leaving one page between). CC and
        CB print the verse and its translation on the same page, so there the
        sloka page *is* the translation page and sloka mode is a no-op.
        """
        return page + 1 if label.startswith("SB ") else page


class Index:
    """Translation index, built once from the PDF outline and cached to disk."""

    def __init__(self, entries: list[Translation]) -> None:
        self.entries = entries
        self.pages = [e.page for e in entries]           # sorted, for bisect
        self.slokas = sorted(e.sloka for e in entries)   # the 's' navigation target

    # -- build / cache ------------------------------------------------------

    @staticmethod
    def _clean(title: str) -> str:
        # strip the "(BR)" / "---" outline decorations, then de-mojibake
        return readable(re.sub(r"^\s*(\(BR\))?\s*-*\s*", "", title).strip())

    @classmethod
    def build(cls, doc: fitz.Document) -> "Index":
        entries: list[Translation] = []
        chapter = ""
        for level, title, page in doc.get_toc():
            if level <= 2:
                c = cls._clean(title)
                if c:
                    chapter = c
            elif level == 4:
                label = cls._clean(title)
                entries.append(Translation(page, label, chapter,
                                           Translation.sloka_page(label, page)))
        entries.sort(key=lambda e: e.page)
        return cls(entries)

    @classmethod
    def load(cls, pdf: Path, doc: fitz.Document) -> "Index":
        cache = pdf.with_suffix(".index.json")
        stat = pdf.stat()
        stamp = {"size": stat.st_size, "mtime": int(stat.st_mtime), "v": 3}

        if cache.exists():
            try:
                blob = json.loads(cache.read_text())
                if blob.get("stamp") == stamp:
                    return cls([Translation(*row) for row in blob["entries"]])
            except (json.JSONDecodeError, KeyError, TypeError):
                pass  # rebuild on any cache corruption

        idx = cls.build(doc)
        cache.write_text(json.dumps({
            "stamp": stamp,
            "entries": [[e.page, e.label, e.chapter, e.sloka] for e in idx.entries],
        }))
        return idx

    # -- queries ------------------------------------------------------------

    def targets(self, sloka: bool) -> list[int]:
        return self.slokas if sloka else self.pages

    def next_after(self, page: int, sloka: bool = False) -> int | None:
        """First target strictly after `page`."""
        t = self.targets(sloka)
        i = bisect.bisect_right(t, page)
        return t[i] if i < len(t) else None

    def prev_before(self, page: int, sloka: bool = False) -> int | None:
        """Last target strictly before `page`."""
        t = self.targets(sloka)
        i = bisect.bisect_left(t, page)
        return t[i - 1] if i > 0 else None

    def at_or_before(self, page: int) -> Translation | None:
        """The verse whose section `page` falls inside — for the status bar."""
        i = bisect.bisect_right(self.pages, page)
        return self.entries[i - 1] if i > 0 else None

    def search(self, query: str, limit: int = 200) -> list[Translation]:
        q = query.lower().strip()
        if not q:
            return []
        terms = q.split()
        out = []
        for e in self.entries:
            hay = e.label.lower()
            if all(t in hay for t in terms):
                out.append(e)
                if len(out) >= limit:
                    break
        return out


# --------------------------------------------------------------------------
# Page view
# --------------------------------------------------------------------------

class PageView(QScrollArea):
    def __init__(self, doc: fitz.Document) -> None:
        super().__init__()
        self.doc = doc
        self.zoom = 1.0
        self.mode = "width"                    # "width" | "height" | "zoom"
        self._page = 1
        self._buf: np.ndarray | None = None   # QImage does not copy; keep it alive

        self.label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.setWidget(self.label)
        self.setWidgetResizable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keys stay with the window
        # hide the scrollbars; scrolling stays keyboard-driven (Up/Down, 'c')
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.set_theme(THEMES[0], DIM_LEVELS[0])

    def set_theme(self, theme: Theme, dim: float) -> None:
        self.theme, self.dim = theme, dim
        self.lut = build_lut(theme, dim)
        # paper = whatever white maps to; use it for the surround so the whole
        # window shifts together instead of the page floating on a grey slab
        self.paper = tuple(int(self.lut[ch][255]) for ch in range(3))
        surround = "#%02x%02x%02x" % self.paper
        self.setStyleSheet(f"background:{surround}; border:0;")
        self.label.setStyleSheet(f"background:{surround};")
        self.render(self._page)

    def _recolour(self, pix: fitz.Pixmap) -> np.ndarray:
        # honour stride: MuPDF may pad rows
        rows = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)
        src = rows[:, : pix.width * 3].reshape(pix.height, pix.width, 3)
        out = np.empty_like(src)
        for ch in range(3):
            np.take(self.lut[ch], src[:, :, ch], out=out[:, :, ch])
        return out

    def _scale_for(self, p: fitz.Page) -> float:
        """Resolve the current fit mode into a render scale."""
        match self.mode:
            case "width":
                return max(200, self.viewport().width() - 24) / p.rect.width
            case "height":
                return max(200, self.viewport().height() - 24) / p.rect.height
            case _:
                return self.zoom

    def fit(self, mode: str) -> None:
        self.mode = mode
        self.render(self._page)

    def zoom_by(self, factor: float) -> None:
        # leaving a fit mode: start from what's on screen, so +/- doesn't jump
        if self.mode != "zoom":
            self.zoom = self._scale_for(self.doc[self._page - 1])
            self.mode = "zoom"
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom * factor))
        self.render(self._page)

    def render(self, page: int) -> None:
        self._page = max(1, min(page, self.doc.page_count))
        p = self.doc[self._page - 1]
        scale = self._scale_for(p)

        dpr = self.devicePixelRatioF()
        pix = p.get_pixmap(matrix=fitz.Matrix(scale * dpr, scale * dpr), alpha=False)

        identity = (self.theme.ink == BLACK and self.theme.paper == WHITE
                    and self.dim == 1.0)
        if identity:
            self._buf = None
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format.Format_RGB888)
        else:
            self._buf = np.ascontiguousarray(self._recolour(pix))
            img = QImage(self._buf.data, pix.width, pix.height, pix.width * 3,
                         QImage.Format.Format_RGB888)

        qp = QPixmap.fromImage(img)
        qp.setDevicePixelRatio(dpr)
        self.label.setPixmap(qp)
        self.verticalScrollBar().setValue(0)

    def centre_h(self) -> None:
        """Put the horizontal scroll exactly in the middle."""
        sb = self.horizontalScrollBar()
        sb.setValue((sb.minimum() + sb.maximum()) // 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.mode in ("width", "height"):   # a fit mode tracks the window
            self.render(self._page)


# --------------------------------------------------------------------------
# Jump palette
# --------------------------------------------------------------------------

class ThemePalette(QWidget):
    """Theme picker. Arrowing through it previews live; Esc puts back what you had."""

    previewed = pyqtSignal(int)   # theme index, as you move through the list
    chosen = pyqtSignal(int)      # committed
    cancelled = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.Popup)
        self.resize(300, 46 + 34 * len(THEMES))

        self.list = QListWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(self.list)
        self.setStyleSheet("""
            QWidget { background:#232323; }
            QListWidget { border:0; font-size:14px; color:#e8e8e8; }
            QListWidget::item { padding:5px; }
            QListWidget::item:selected { background:#3a5a8c; }
        """)

        for i, th in enumerate(THEMES):
            # swatch: the theme's paper with its ink written on it
            pm = QPixmap(46, 22)
            pm.fill(QColor(*th.paper))
            p = QPainter(pm)
            p.setPen(QColor(*th.ink))
            p.setFont(QFont("Georgia", 12))
            p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "Aa")
            p.end()
            it = QListWidgetItem(QIcon(pm), f"  {i + 1}   {th.name}")
            it.setData(Qt.ItemDataRole.UserRole, i)
            self.list.addItem(it)
        self.list.setIconSize(QSize(46, 22))

        self.list.currentRowChanged.connect(
            lambda r: self.previewed.emit(r) if r >= 0 else None)
        self.list.itemActivated.connect(lambda _: self._accept())

    def open(self, current: int) -> None:
        self._restore_to = current
        self._committed = False
        self.list.setCurrentRow(current)
        self.show()
        self.list.setFocus()

    def _accept(self) -> None:
        self._committed = True
        self.chosen.emit(self.list.currentRow())
        self.hide()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        k = e.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._accept()
        elif k == Qt.Key.Key_Escape:
            self.hide()
        elif Qt.Key.Key_1 <= k <= Qt.Key.Key_9 and k - Qt.Key.Key_1 < len(THEMES):
            self.list.setCurrentRow(k - Qt.Key.Key_1)
            self._accept()
        else:
            super().keyPressEvent(e)

    def hideEvent(self, e) -> None:
        if not self._committed:          # dismissed -> undo the live preview
            self.cancelled.emit()
        super().hideEvent(e)


class JumpPalette(QWidget):
    chosen = pyqtSignal(int)

    def __init__(self, index: Index) -> None:
        super().__init__()
        self.index = index
        self.setWindowFlags(Qt.WindowType.Popup)
        self.resize(560, 420)

        self.box = QLineEdit(placeholderText="Jump to verse…  e.g.  SB 1.1.1   ·   Madhya 20.268   ·   CBAdi 10.112")
        self.list = QListWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(self.box)
        lay.addWidget(self.list)

        self.setStyleSheet("""
            QWidget   { background:#232323; color:#e8e8e8; }
            QLineEdit { padding:9px; font-size:15px; border:1px solid #3d3d3d;
                        border-radius:6px; background:#1a1a1a; }
            QListWidget { border:0; font-size:14px; }
            QListWidget::item { padding:6px 4px; }
            QListWidget::item:selected { background:#3a5a8c; }
        """)

        self.box.textChanged.connect(self._refresh)
        self.box.returnPressed.connect(self._accept)
        self.list.itemActivated.connect(lambda _: self._accept())

    def open(self) -> None:
        self.box.clear()
        self.list.clear()
        self.show()
        self.box.setFocus()

    def _refresh(self, text: str) -> None:
        self.list.clear()
        for e in self.index.search(text, limit=200):
            it = QListWidgetItem(f"{e.label}      —  {e.chapter}      (p.{e.page:,})")
            it.setData(Qt.ItemDataRole.UserRole, e.page)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _accept(self) -> None:
        it = self.list.currentItem()
        if it:
            self.chosen.emit(it.data(Qt.ItemDataRole.UserRole))
            self.hide()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        # let Up/Down drive the list while focus sits in the text box
        if e.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            row = self.list.currentRow() + (1 if e.key() == Qt.Key.Key_Down else -1)
            if 0 <= row < self.list.count():
                self.list.setCurrentRow(row)
            return
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(e)


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------

class Reader(QMainWindow):
    def __init__(self, pdf: Path) -> None:
        super().__init__()
        self.doc = fitz.open(pdf)
        self.index = Index.load(pdf, self.doc)
        self.state_file = pdf.with_suffix(".state.json")
        (self.page, self.theme_i, self.dim_i, mode, zoom,
         show_bar, self.sloka) = self._restore()

        self.view = PageView(self.doc)
        self.view.mode, self.view.zoom = mode, zoom
        self._apply_colour()

        # status bar: verse on the left, page counter pinned right
        self.status_left = QLabel()
        self.status_right = QLabel()
        self.bar = QWidget()
        self.bar.setStyleSheet("background:#111;")
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(12, 7, 12, 7)
        bl.addWidget(self.status_left)
        bl.addStretch(1)
        bl.addWidget(self.status_right)
        for lbl in (self.status_left, self.status_right):
            lbl.setStyleSheet("color:#bdbdbd; font-size:13px;")
        self.bar.setVisible(show_bar)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.bar)
        self.setCentralWidget(central)

        self.palette_ = JumpPalette(self.index)
        self.palette_.chosen.connect(self.goto)

        self.themes = ThemePalette()
        self.themes.previewed.connect(lambda i: self.set_theme(i, flash=False))
        self.themes.chosen.connect(self.set_theme)
        self.themes.cancelled.connect(
            lambda: self.set_theme(self.themes._restore_to, flash=False))

        # coalesce state writes: holding a key turns ~4 pages/sec, and each one
        # would otherwise hit the disk
        self._save_soon = QTimer(self, singleShot=True)
        self._save_soon.timeout.connect(self._save)

        self.setWindowTitle("SB · CC · CB Reader")
        self.resize(1000, 900)
        self.goto(self.page)

    # -- navigation ---------------------------------------------------------

    def goto(self, page: int) -> None:
        self.page = max(1, min(page, self.doc.page_count))
        self.view.render(self.page)
        self._sync_status()
        self._save_soon.start(600)

    def step_page(self, delta: int) -> None:
        self.goto(self.page + delta)

    # -- colour ladder ------------------------------------------------------

    def _apply_colour(self) -> None:
        self.view.set_theme(THEMES[self.theme_i], DIM_LEVELS[self.dim_i])

    def set_theme(self, i: int, *, flash: bool = True) -> None:
        self.theme_i = i % len(THEMES)
        self._apply_colour()
        if flash:
            self._flash(f"{THEMES[self.theme_i].name} · {self.dim_i + 1}/{len(DIM_LEVELS)}")
            self._save_soon.start(600)

    def step_brightness(self, delta: int) -> None:
        """+1 = brighter, -1 = dimmer. Clamps at the ends."""
        new = min(len(DIM_LEVELS) - 1, max(0, self.dim_i - delta))
        if new == self.dim_i:
            self._flash("Brightest" if delta > 0 else "Dimmest")
            return
        self.dim_i = new
        self._apply_colour()
        self._flash(f"{THEMES[self.theme_i].name} · {self.dim_i + 1}/{len(DIM_LEVELS)}")
        self._save_soon.start(600)

    def step_translation(self, delta: int) -> None:
        target = (self.index.next_after(self.page, self.sloka) if delta > 0
                  else self.index.prev_before(self.page, self.sloka))
        if target is None:
            self._flash("Start of book" if delta < 0 else "End of book")
            return
        self.goto(target)

    def toggle_sloka(self) -> None:
        """Aim left/right at the sloka instead of the translation.

        Only changes anything for SB, where the sloka is its own page. CC and CB
        print verse and translation together, so there both modes land alike.
        """
        self.sloka = not self.sloka
        self._flash("Sloka" if self.sloka else "Translation")
        self._save_soon.start(600)

    def random_translation(self) -> None:
        """Enter -> land on a random verse, honouring the current target."""
        e = random.choice(self.index.entries)
        target = e.sloka if self.sloka else e.page
        if len(self.index.entries) > 1 and target == self.page:
            e = random.choice(self.index.entries)   # one retry; don't sit still
            target = e.sloka if self.sloka else e.page
        self.goto(target)
        self._flash("Random")

    def _sync_status(self, note: str = "") -> None:
        e = self.index.at_or_before(self.page)
        here = f"<b style='color:#f0f0f0'>{e.label}</b> &nbsp;·&nbsp; {e.chapter}" if e else "—"
        off = f" <span style='color:#777'>(+{self.page - e.page})</span>" if e and self.page > e.page else ""
        tail = f" &nbsp; <span style='color:#e0b050'>{note}</span>" if note else ""
        self.status_left.setText(here + off + tail)
        mode = ("<span style='color:#e0b050'>SLOKA</span> &nbsp; " if self.sloka else "")
        self.status_right.setText(
            f"{mode}<span style='color:#777'>page</span> "
            f"{self.page:,} / {self.doc.page_count:,}"
        )

    def _flash(self, msg: str) -> None:
        self._sync_status(msg)
        QTimer.singleShot(1200, self._sync_status)

    # -- persistence --------------------------------------------------------

    def _restore(self) -> tuple[int, int, int, str, float, bool, bool]:
        try:
            blob = json.loads(self.state_file.read_text())
            page = int(blob["page"])
            if "colour" in blob:                       # migrate the old fused index
                old = int(blob["colour"])
                theme_i, dim_i = old // len(DIM_LEVELS), old % len(DIM_LEVELS)
            else:
                theme_i = int(blob.get("theme", 0))
                dim_i = int(blob.get("dim", 0))
            theme_i = theme_i % len(THEMES)
            dim_i = min(len(DIM_LEVELS) - 1, max(0, dim_i))
            mode = blob.get("mode", "width")
            if mode not in ("width", "height", "zoom"):
                mode = "width"
            zoom = min(ZOOM_MAX, max(ZOOM_MIN, float(blob.get("zoom", 1.0))))
            return (page, theme_i, dim_i, mode, zoom,
                    bool(blob.get("bar", False)), bool(blob.get("sloka", False)))
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
            # page 1, Normal at full brightness, fit width, bar hidden, translation mode
            return 1, 0, 0, "width", 1.0, False, False

    def _save(self) -> None:
        try:
            self.state_file.write_text(json.dumps({
                "page": self.page,
                "theme": self.theme_i,
                "dim": self.dim_i,
                "mode": self.view.mode,
                "zoom": self.view.zoom,
                "bar": self.bar.isVisible(),
                "sloka": self.sloka,
            }))
        except OSError:
            pass

    def closeEvent(self, e) -> None:
        self._save()  # flush whatever the debounce still owes
        super().closeEvent(e)

    # -- key handling -------------------------------------------------------

    def keyPressEvent(self, e: QKeyEvent) -> None:
        k = e.key()

        # Arrows navigate; allow OS auto-repeat so holding a key keeps moving.
        # Up/Down = translation (Down forward), Left/Right = page (Right forward).
        match k:
            case Qt.Key.Key_Down:
                self.step_translation(+1); return
            case Qt.Key.Key_Up:
                self.step_translation(-1); return
            case Qt.Key.Key_Right:
                self.step_page(+1); return
            case Qt.Key.Key_Left:
                self.step_page(-1); return

        if e.isAutoRepeat():
            return  # everything below is a discrete action, not a hold

        # Cmd (macOS) / Ctrl (Linux) + , = dimmer, + . = brighter
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if k == Qt.Key.Key_Period:
                self.step_brightness(+1)
                return
            if k == Qt.Key.Key_Comma:
                self.step_brightness(-1)
                return

        # 1..9 pick a theme outright
        if Qt.Key.Key_1 <= k <= Qt.Key.Key_9 and k - Qt.Key.Key_1 < len(THEMES):
            self.set_theme(k - Qt.Key.Key_1)
            return

        match k:
            case Qt.Key.Key_Return | Qt.Key.Key_Enter:
                self.random_translation()
            case Qt.Key.Key_C:
                self.view.centre_h()
            case Qt.Key.Key_S:
                self.toggle_sloka()
            case Qt.Key.Key_T:
                self.themes.move(self.geometry().center() - self.themes.rect().center())
                self.themes.open(self.theme_i)
            case Qt.Key.Key_PageDown | Qt.Key.Key_Space:
                self.step_page(+1)
            case Qt.Key.Key_PageUp:
                self.step_page(-1)
            case Qt.Key.Key_Home:
                self.goto(1)
            case Qt.Key.Key_End:
                self.goto(self.doc.page_count)
            case Qt.Key.Key_G | Qt.Key.Key_Slash:
                self.palette_.move(self.geometry().center() - self.palette_.rect().center())
                self.palette_.open()
            case Qt.Key.Key_Plus | Qt.Key.Key_Equal:
                self.view.zoom_by(1.15)
                self._flash(f"Zoom {self.view.zoom:.0%}")
                self._save_soon.start(600)
            case Qt.Key.Key_Minus:
                self.view.zoom_by(1 / 1.15)
                self._flash(f"Zoom {self.view.zoom:.0%}")
                self._save_soon.start(600)
            case Qt.Key.Key_W | Qt.Key.Key_0:
                self.view.fit("width")
                self._flash("Fit width")
                self._save_soon.start(600)
            case Qt.Key.Key_H:
                self.view.fit("height")
                self._flash("Fit height")
                self._save_soon.start(600)
            case Qt.Key.Key_I:
                self.bar.setVisible(not self.bar.isVisible())
                self._save_soon.start(600)
            case Qt.Key.Key_F:
                self.showNormal() if self.isFullScreen() else self.showFullScreen()
            case Qt.Key.Key_Q | Qt.Key.Key_Escape:
                self.close()
            case _:
                super().keyPressEvent(e)


def main() -> int:
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / PDF_NAME
    if not pdf.exists():
        print(f"PDF not found: {pdf}", file=sys.stderr)
        return 1

    app = QApplication(sys.argv)
    win = Reader(pdf)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
