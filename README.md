# SB · CC · CB Reader

A desktop reader for `SB_CC_CB_ALL_NEW_INDEX_Oct3_2021.pdf` — the same navigation
model as the Android app, built on the same engine (MuPDF, via PyMuPDF).

Runs on macOS and Linux.

## The PDF

The book itself (`SB_CC_CB_ALL_NEW_INDEX_Oct3_2021.pdf`, ~538 MB) is **not** in
this repo — it is far past GitHub's file-size limit. Download it and drop it in
the project root next to `reader.py`:

<https://drive.google.com/file/d/186cFWCiBbdWzaIP6EMdEyM1cqCSW-qX5/view?usp=drive_link>

## Run

```sh
uv run python reader.py
```

Point it at a different PDF, or the file elsewhere, with
`uv run python reader.py /path/to/SB_CC_CB_ALL_NEW_INDEX_Oct3_2021.pdf`.

## Generated files

None of these are in git — they're rebuilt from the PDF. Only one of them is
precious.

| File | Size | Purpose | Safe to delete? |
| --- | --- | --- | --- |
| `*.state.json` | ~100 B | your bookmark + preferences | yes |
| `*.pages.json` | ~3 MB | the map of the book | only if you can re-run the build |
| `*.index.json` | ~3 MB | cached outline parse | yes |

**`*.state.json` — so the app remembers you.** Its whole purpose is continuity
across restarts: last page, theme, brightness, fit mode, nav mode, random scope.
Without it every launch would dump you at page 1 with the defaults. Purely a
convenience — delete it and you lose only your place. One per PDF, since page
numbers differ between files.

**`*.pages.json` — so the reader can think in verses, not pages.** Written by
`build_interleaved.py`; maps each of the 36,137 verses to its translation /
sloka / interleaved page (`-1` where a verse has none). This is what makes `s`,
`g` and `Enter` work. It exists for two reasons:

1. **The interleaved page numbers exist nowhere else.** Interleaved pages are
   appended at the *tail* of the PDF — page 245731 contains nothing saying "I
   belong to SB 10.44.6". Only the build knew that when it drew the page, so it
   writes the mapping down; otherwise the knowledge dies with the build and the
   reader could never offer interleaved mode at all.
2. **Speed.** The translation/sloka pages *could* be re-derived from the PDF's
   58,520 bookmarks, but that costs ~2 s every launch. Reading flat JSON is
   instant.

So it's the bridge between the build and the reader. Regenerable, but only by
re-running the ~33 min build.

**`*.index.json` — the fallback.** The older cache, built by parsing the PDF
outline (~2 s) the first time a PDF is opened. Used for the original PDF, which
has no `.pages.json`. The reader prefers `.pages.json` whenever it exists.

## Keys

Forward is **down / right**.

| Key | Action |
| --- | --- |
| `↓` | **next** translation |
| `↑` | previous translation |
| `→` | **next** page |
| `←` | previous page |
| mouse wheel | scroll within the page |
| `Enter` | **random** verse (from the chosen scope, in the current nav mode) |
| `r` | choose which cantos/sections `Enter` draws from |
| `s` | cycle nav mode: translation → sloka → interleaved |
| `Space` / `PgDn` | one page forward |
| `PgUp` | one page back |
| `t` | theme picker |
| `⌘.` / `⌘,` | brighter / dimmer (hold to ramp) |
| `i` | show / hide the status bar (hidden by default) |
| `g` or `/` | jump to a verse |
| `w` | fit to width |
| `h` | fit to height |
| `c` | centre the page horizontally |
| `+` / `−` | zoom in / out |
| `0` | fit to width (same as `w`) |
| `f` | fullscreen (cursor auto-hides when idle) |
| `Home` / `End` | first / last page |
| `q` / `Esc` | quit |

Up/Down step verse-to-verse (by translation, or by sloka with `s` on); Left/Right
step one page at a time. Holding any arrow auto-repeats, so you can hold to run
through verses or pages. Within a tall page, scroll with the mouse wheel — the
scrollbars are hidden.

`w` and `h` are sticky: the page keeps re-fitting as you resize the window and
as you move between pages. Page heights in this PDF vary a lot (370–1035 pt at a
constant 429 pt width), so fit-height re-scales noticeably page to page while
fit-width stays put. `+`/`−` resumes from whatever is currently on screen rather
than snapping to some other scale, and drops you into free-zoom. The mode is
remembered between runs.

## Nav mode: translation / sloka / interleaved

`s` cycles what up/down (and `Enter`) land on for the current verse:

1. **Translation** — the English translation page (default)
2. **Sloka** — the Sanskrit verse page
3. **Interleaved** — a page where each transliteration pada is paired with its
   enlarged Devanagari (SB only; see below)

The status bar shows `SLOKA` / `INTERLEAVED` when you're on one, and the mode is
remembered between runs. `s` skips modes a verse doesn't have: CC/CB print verse
and translation on one page (so only translation), and SB verses without an
interleaved page cycle just translation ↔ sloka.

### The enhanced pages

An enhanced page is added for every SB verse, right after its sloka:

- **Interleaved** (~97% of SB) — each transliteration pada above its enlarged
  1.5× Devanagari. See [interleave.py](interleave.py): transliteration on top,
  `//`-joined padas for older-canto verses, wrapped padas re-joined, a leading
  `… uväca` speaker line paired 1:1.
- **Enlarged sloka** (the rest, where the counts don't pair) — the whole
  Devanagari block enlarged 1.5×, then the transliteration, then word-for-word
  and translation. Same idea, just not line-paired.

CC/CB verses have no Devanagari in this edition (the verse is printed only in
transliteration), so they get no enhanced page.

### Building it — two steps

```sh
uv run python build_interleaved.py   # 1) draw the interleaved pages (~35 min)
uv run python build_inline.py        # 2) splice inline + add outline (~2 min, needs qpdf)
```

1. **`build_interleaved.py`** appends one interleaved page per verse at the *tail*
   of the PDF and writes `…_interleaved.pdf` + a sidecar. Fast to write
   (incremental save) but the enhanced pages aren't in reading order — fine for
   this reader (it uses the sidecar), wrong for a plain PDF viewer.
2. **`build_inline.py`** produces the **shippable** `…_inline.pdf` (≈693 MB,
   250,298 pages): it reuses those interleaved pages, draws the enlarged-sloka
   fallbacks, and uses **qpdf** to splice each enhanced page physically after its
   sloka — so the book reads sloka → enhanced → purport in *any* PDF viewer. It
   also rebuilds the outline (bookmarks / table of contents), which qpdf drops:
   the original canto → chapter → verse tree with corrected page numbers, plus a
   `» interleaved` entry under each verse that jumps to its enhanced page. So the
   shipped PDF is self-contained — pages in order **and** a working table of
   contents, no app or sidecar needed.
   (`brew install qpdf` / `apt install qpdf`. PyMuPDF and pikepdf both assemble a
   250k-page tree in O(n²) — hours; qpdf does it by reference in ~2 min.)

The reader opens `…_inline.pdf` if present, else `…_interleaved.pdf`, else the
original. Each build writes its own `.pages.json` sidecar mapping every verse to
its translation / sloka / enhanced page.

## Colours

Nineteen themes, each with **30 brightness steps**. Press `t` for the picker.

| # | Theme | Page | Letters |
| --- | --- | --- | --- |
| 1 | Normal *(default)* | white | black |
| 2 | Inverted | dark | white |
| 3 | Green | green | black |
| 4 | Orange | orange | black |
| 5 | Solarized | `#fdf6e3` base3 | `#657b83` base00 |
| 6 | Solar Dark | `#002b36` base03 | `#839496` base0 |
| 7 | Monokai | `#272822` | `#f8f8f2` |
| 8 | Mariana | `#343d46` | `#d8dee9` |
| 9 | Sepia | `#f4ecd8` | black |
| 10 | Red | `#390000` | `#f8f8f8` |
| 11 | Dark+ | `#1e1e1e` | `#d4d4d4` |
| 12 | Dark Modern | `#1f1f1f` | `#cccccc` |
| 13 | Abyss | `#000c18` | `#6688cc` |
| 14 | Tomorrow Night Blue | `#002451` | `#ffffff` |
| 15 | Kimbie Dark | `#221a0f` | `#d3af86` |
| 16 | Monokai Dimmed | `#1e1e1e` | `#c5c8c6` |
| 17 | Quiet Light | `#f5f5f5` | `#333333` |
| 18 | Light Modern | `#ffffff` | `#3b3b3b` |
| 19 | Light High Contrast | `#ffffff` | `#292929` |

Monokai is Sublime Text's classic default scheme; Mariana is its newer one.
10-19 are VS Code's built-in schemes (editor foreground on editor background).
VS Code's Light+ and Dark High Contrast are identical to Normal and Inverted, and
Dark (Visual Studio) to Dark+, so they aren't duplicated.

Brightness is separate from the theme: `⌘.` brightens, `⌘,` dims, clamping at
either end (Linux: `Ctrl`). Hold either to ramp through the 30 steps. Changing theme keeps your brightness rather than
resetting it. The current state shows in the status bar (`Monokai · 3/30`) and is
remembered between runs.

In the picker, arrowing through the list **previews each theme live** on the
page behind it; `Enter` commits, `Esc` puts back what you had.

Each theme is an *ink → paper* ramp applied per channel: source black becomes
`ink`, source white becomes `paper`, everything between interpolates. Doing it
per channel rather than off a single luminance keeps the page's own colour, so
the gold headings tint along instead of flattening to grey. (For the black-ink
themes this is exactly a multiply by the paper colour.) Solarized needs the
`ink` term because its text is a slate grey, not black.

Contrast narrows at the dim end — sharpest for Green and Orange at 30/30, where
the paper darkens while the letters stay pure black. Widen or re-grain the range
with `DIM_FLOOR` / `DIM_STEPS` in `reader.py`; the palettes themselves are the
`THEMES` tuple right above, and adding another is one more line.

## Jump to a verse

Press `g`, then type a reference — matching is substring-based across all
36,137 verses, so partial input is fine:

```
SB 1.1.1        Madhya 20.268        CBAdi 10.112        Antya 4.168
```

`↑`/`↓` to pick, `Enter` to go, `Esc` to dismiss.

## Random scope

`Enter` jumps to a random verse. Press `r` to choose which parts of the corpus
it draws from — a checkbox tree of **SB cantos 1–12**, **CC** (Adi / Madhya /
Antya) and **CB** (Adi / Madhya / Antya), each with its verse count. Check a
whole book's box to toggle all its sections. **All** resets to the full corpus.
The scope persists between runs, and the status bar shows it when you press
`Enter` (e.g. `Random · SB Canto 1`).

## How "next translation" works

The PDF is a slideshow: 237,298 pages, where a single verse spans ~40 of them
(breakup slides → translation → sloka → purport slides `[1/32]`, `[2/32]`…).

Its outline has four levels, and **level 4 is exactly the translation page** of
each verse:

```
L1  Canto 1: Creation
L2  SB 1.1: Questions by the Sages
L3    (BR)--- SB 1.1.1 / 23     <- (BR) = breakup slides       p.9
L4    --- SB 1.1.1 / 23         <- ENGLISH TRANSLATION         p.10
L3    PURPORT                                                  p.12
```

So the reader pulls all 36,137 level-4 entries, sorts them by page, and a tap
does a binary search for the next one. Level 1/2 headings ride along as the
chapter shown in the status bar. Covers SB, CC (Adi/Madhya/Antya) and CB
(CBAdi/CBMad/CBAnt).

## Enhanced-page coverage (SB)

Of the 13,004 SB verses, 13,000 get an enhanced page — the split is exact, not a
rounding:

| | count |
| --- | --- |
| SB verses total | **13,004** |
| interleaved | 12,653 |
| enlarged-sloka fallback | 347 |
| **enhanced pages** | **13,000** |
| no enhanced page | **4** |

The 4 without one — **SB 10.8.1, 10.8.17, 10.8.28, 10.11.21** — have no Devanagari
at all on their page in the source PDF. What's actually printed on SB 10.8.1's
sloka page is transliteration only:

```
… SB 10.8.1 / 52   çré-çuka uväca   gargaù purohito räjan …
```

With no Devanagari to interleave or enlarge, they get no enhanced page. It's a
gap in the source edition, not something the build dropped.
