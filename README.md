# SB · CC · CB Reader

A desktop reader for `SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline_interleaved.pdf` — the same navigation
model as the Android app, built on the same engine (MuPDF, via PyMuPDF).

Runs on macOS and Linux.

## The PDF

The PDFs are **not** in this repo (far past GitHub's file-size limit). Download
one from Google Drive and drop it in the project root next to `reader.py`:

- **Ready-to-use interleaved book** — `SB_CC_CB_ALL_NEW_INDEX_Oct3_2021_inline_interleaved.pdf`
  (~700 MB, 250,302 pages). The finished, shippable file: pages in reading order
  with the interleaved/enhanced page after each sloka, plus a working outline.
  Just download and run — nothing else needed.
  <https://drive.google.com/file/d/1k3LtAIs6cjga4e4uxo07PJLQmUgX9q8l/view?usp=drive_link>

- **Original source book** — `SB_CC_CB_ALL_NEW_INDEX_Oct3_2021.pdf` (~538 MB).
  Only needed to *regenerate* the interleaved PDF (see [`pre_processing/`](pre_processing/)).
  <https://drive.google.com/file/d/186cFWCiBbdWzaIP6EMdEyM1cqCSW-qX5/view?usp=drive_link>

The reader opens whichever it finds, preferring the interleaved one.

## Run

This uses [uv](https://docs.astral.sh/uv/) to manage everything — on first launch
`uv run` downloads the right Python (3.12+, pinned in `.python-version`) *and*
installs the dependencies, so **`uv` is the only thing you need** — no separate
Python install. If you don't have `uv`, install it once:

```sh
# macOS / Linux (recommended — a standalone binary, needs no Python)
curl -LsSf https://astral.sh/uv/install.sh | sh
# macOS (Homebrew)
brew install uv
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# or, if you already have Python/pip
pip install uv
```

The `curl` installer drops `uv` in `~/.local/bin`. After it finishes, open a new
terminal — or reload your shell so it's on your `PATH`:

```sh
source ~/.bashrc     # Ubuntu / most Linux
source ~/.zshrc      # macOS
```

Check it worked:

```sh
uv --version
```

Then run the reader:

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
| `*.pages.json` | ~3 MB | the map of the book (optional for the inline PDF) | see below |
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

So it's the bridge between the build and the reader — **except for the inline
PDF**, which carries the same information in its outline (the `»` bookmark under
each verse). The reader reads that when no sidecar is present, so the inline PDF
works fully in the app *and* in any viewer with just the `.pdf` — no sidecar
needed. (The sidecar, if kept, just skips a ~2 s outline parse at startup.) The
*tail* `…_interleaved.pdf` still needs its sidecar, since its outline is stale.

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
| `Shift`+`↑`/`↓` | fine scroll |
| `Shift`+`Ctrl`+`↑`/`↓` | scroll more (3×) |
| `Enter` | **random** verse (from the chosen scope, in the current nav mode) |
| `r` | choose which cantos/sections `Enter` draws from |
| `s` | cycle nav mode: translation → sloka → interleaved |
| `Space` / `PgDn` | one page forward |
| `PgUp` | one page back |
| `t` | theme picker |
| `⌘.` / `⌘,` | brighter / dimmer (hold to ramp) |
| `i` | show / hide the status bar (hidden by default) |
| `g` or `/` | jump to a verse |
| `p` | save this page (in the current theme) as a PNG in `Downloads/`, named by verse |
| `b` | bookmark this verse (press again to remove) |
| `Shift`+`B` | bookmark list — recent first; Enter opens, Del removes |
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
  1.5× Devanagari. See [interleave.py](pre_processing/interleave.py): transliteration on top,
  `//`-joined padas for older-canto verses, wrapped padas re-joined, a leading
  `… uväca` speaker line paired 1:1.
- **Enlarged sloka** (the rest, where the counts don't pair) — the whole
  Devanagari block enlarged 1.5×, then the transliteration, then word-for-word
  and translation. Same idea, just not line-paired.

CC/CB verses have no Devanagari in this edition (the verse is printed only in
transliteration), so they get no enhanced page.

### Building it — two steps

The reader (`reader.py`) is standalone; the build scripts live in
[`pre_processing/`](pre_processing/) and are only needed to (re)generate the PDF.


```sh
uv run python pre_processing/build_interleaved.py   # 1) draw the interleaved pages (~35 min)
uv run python pre_processing/build_inline.py       # 2) splice inline + add outline (~2 min, needs qpdf)
```

1. **`build_interleaved.py`** appends one interleaved page per verse at the *tail*
   of the PDF and writes `…_interleaved.pdf` + a sidecar. Fast to write
   (incremental save) but the enhanced pages aren't in reading order — fine for
   this reader (it uses the sidecar), wrong for a plain PDF viewer.
2. **`build_inline.py`** produces the **shippable** `…_inline_interleaved.pdf` (≈693 MB,
   250,302 pages): it reuses those interleaved pages, draws the enlarged-sloka
   fallbacks, and uses **qpdf** to splice each enhanced page physically after its
   sloka — so the book reads sloka → enhanced → purport in *any* PDF viewer. It
   also rebuilds the outline (bookmarks / table of contents), which qpdf drops:
   the original canto → chapter → verse tree with corrected page numbers, plus a
   `» interleaved` entry under each verse that jumps to its enhanced page. So the
   shipped PDF is self-contained — pages in order **and** a working table of
   contents, no app or sidecar needed.
   (`brew install qpdf` / `apt install qpdf`. PyMuPDF and pikepdf both assemble a
   250k-page tree in O(n²) — hours; qpdf does it by reference in ~2 min.)

The reader opens `…_inline_interleaved.pdf` if present, else `…_interleaved.pdf`, else the
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
| sloka-copy | 4 |
| **enhanced pages** | **13,004** |

Every SB verse gets an enhanced page after its sloka, so the order is uniform
(sloka → enhanced) with no gaps. Four verses — **SB 10.8.1, 10.8.17, 10.8.28,
10.11.21** — have no Devanagari at all in the source (their verse is printed only
in transliteration, e.g. `çré-çuka uväca gargaù purohito räjan …`). With nothing
to interleave or enlarge, their enhanced page is just a copy of the sloka page,
so the sloka → enhanced pattern still holds.

### The 347 enlarged-sloka verses

These SB verses couldn't be line-paired (irregular Devanagari/transliteration
line counts), so they get the enlarged-Devanagari fallback instead of a true
interleaved page. By canto: 1 (7), 2 (6), 3 (10), 4 (18), **5 (234)**, 6 (27),
7 (11), 8 (11), 9 (11), 10 (7), 11 (3), 12 (2) — Canto 5 dominates because its
prose passages pack padas irregularly.

<details><summary>Full list (347)</summary>

```
SB 1.1.6, SB 1.7.49, SB 1.8.9, SB 1.12.18, SB 1.12.19, SB 1.17.22, SB 1.18.11, SB 2.1.22
SB 2.4.5, SB 2.5.9, SB 2.6.1, SB 2.8.1, SB 2.9.25, SB 3.1.3, SB 3.13.9, SB 3.15.3
SB 3.15.12, SB 3.16.1, SB 3.16.13, SB 3.16.16, SB 3.16.27, SB 3.18.22-23, SB 3.24.12, SB 4.1.26-27
SB 4.1.30, SB 4.6.42, SB 4.7.40, SB 4.8.54, SB 4.8.65, SB 4.12.23, SB 4.13.31, SB 4.14.14
SB 4.15.3, SB 4.21.21, SB 4.22.42, SB 4.23.25, SB 4.25.5, SB 4.26.17, SB 4.29.54, SB 4.29.56
SB 4.31.5, SB 5.1.1, SB 5.1.5, SB 5.1.6, SB 5.1.8, SB 5.1.20, SB 5.1.24, SB 5.1.26
SB 5.1.27, SB 5.1.29, SB 5.1.30, SB 5.1.33, SB 5.1.39, SB 5.2.1, SB 5.2.5, SB 5.2.6
SB 5.2.18, SB 5.2.19, SB 5.2.21, SB 5.2.23, SB 5.3.2, SB 5.3.3, SB 5.3.4-5, SB 5.3.9
SB 5.3.12, SB 5.3.15, SB 5.3.17, SB 5.3.20, SB 5.4.1, SB 5.4.4, SB 5.4.5, SB 5.4.6
SB 5.4.8, SB 5.4.14, SB 5.4.18, SB 5.4.19, SB 5.5.28, SB 5.5.30, SB 5.5.31, SB 5.5.32
SB 5.5.35, SB 5.6.1, SB 5.6.3, SB 5.6.7, SB 5.6.9, SB 5.6.10, SB 5.6.16, SB 5.7.1
SB 5.7.2, SB 5.7.6, SB 5.7.7, SB 5.7.8, SB 5.7.11, SB 5.7.12, SB 5.7.13, SB 5.8.7
SB 5.8.8, SB 5.8.9, SB 5.8.12, SB 5.8.20, SB 5.8.23, SB 5.8.24, SB 5.8.25, SB 5.8.26
SB 5.8.27, SB 5.8.31, SB 5.9.1-2, SB 5.9.3, SB 5.9.4, SB 5.9.5, SB 5.9.6, SB 5.9.9-10
SB 5.9.11, SB 5.9.13, SB 5.9.14, SB 5.9.15, SB 5.9.17, SB 5.9.18, SB 5.9.20, SB 5.10.1
SB 5.10.2, SB 5.10.5, SB 5.10.6, SB 5.10.8, SB 5.10.14, SB 5.10.15, SB 5.13.24, SB 5.13.25
SB 5.13.26, SB 5.14.1, SB 5.14.2, SB 5.14.4, SB 5.14.18, SB 5.14.21, SB 5.14.28, SB 5.14.29
SB 5.14.30, SB 5.14.31, SB 5.14.36, SB 5.14.38, SB 5.14.40, SB 5.14.41, SB 5.14.42, SB 5.14.46
SB 5.15.1, SB 5.15.6, SB 5.15.7, SB 5.15.14-15, SB 5.15.16, SB 5.16.2, SB 5.16.4, SB 5.16.7
SB 5.16.8, SB 5.16.9, SB 5.16.10, SB 5.16.13-14, SB 5.16.17, SB 5.16.19, SB 5.16.20-21, SB 5.16.22
SB 5.16.24, SB 5.16.26, SB 5.16.27, SB 5.16.28, SB 5.17.1, SB 5.17.2, SB 5.17.3, SB 5.17.5
SB 5.17.9, SB 5.17.11, SB 5.17.12, SB 5.17.13, SB 5.17.14, SB 5.17.15, SB 5.17.16, SB 5.18.1
SB 5.18.7, SB 5.18.8, SB 5.18.15, SB 5.18.18, SB 5.18.29, SB 5.18.30, SB 5.19.3, SB 5.19.9
SB 5.19.10, SB 5.19.16, SB 5.19.17-18, SB 5.19.19, SB 5.19.20, SB 5.19.29-30, SB 5.20.2, SB 5.20.3-4
SB 5.20.9, SB 5.20.11, SB 5.20.14, SB 5.20.15, SB 5.20.20, SB 5.20.21, SB 5.20.22, SB 5.20.24
SB 5.20.25, SB 5.20.26, SB 5.20.27, SB 5.20.29, SB 5.20.30, SB 5.20.37, SB 5.20.40, SB 5.20.42
SB 5.21.3, SB 5.21.7, SB 5.21.8-9, SB 5.21.11, SB 5.21.13, SB 5.21.15, SB 5.21.18, SB 5.22.2
SB 5.22.3, SB 5.22.5, SB 5.22.7, SB 5.22.8, SB 5.22.9, SB 5.22.12, SB 5.22.13, SB 5.22.16
SB 5.23.1, SB 5.23.3, SB 5.23.5, SB 5.23.6, SB 5.23.7, SB 5.23.8, SB 5.24.1, SB 5.24.2
SB 5.24.3, SB 5.24.7, SB 5.24.8, SB 5.24.9, SB 5.24.10, SB 5.24.16, SB 5.24.17, SB 5.24.18
SB 5.24.19, SB 5.24.24, SB 5.24.25, SB 5.24.27, SB 5.24.28, SB 5.24.29, SB 5.24.30, SB 5.24.31
SB 5.25.1, SB 5.25.4, SB 5.25.5, SB 5.25.7, SB 5.25.8, SB 5.25.15, SB 5.26.3, SB 5.26.7
SB 5.26.8, SB 5.26.9, SB 5.26.10, SB 5.26.14, SB 5.26.15, SB 5.26.16, SB 5.26.17, SB 5.26.18
SB 5.26.22, SB 5.26.24, SB 5.26.28, SB 5.26.29, SB 5.26.30, SB 5.26.32, SB 5.26.33, SB 5.26.35
SB 5.26.36, SB 5.26.37, SB 5.26.38, SB 6.1.9, SB 6.1.38, SB 6.1.40, SB 6.2.2, SB 6.3.4
SB 6.4.1-2, SB 6.7.1, SB 6.7.21, SB 6.7.27, SB 6.8.1-2, SB 6.8.8-10, SB 6.9.31, SB 6.9.33
SB 6.9.35, SB 6.9.36, SB 6.9.39, SB 6.9.40, SB 6.9.41, SB 6.9.42, SB 6.10.5, SB 6.13.3
SB 6.13.8-9, SB 6.15.10, SB 6.16.25, SB 6.18.20, SB 6.19.1, SB 6.19.7, SB 7.1.1, SB 7.2.29-31
SB 7.3.17, SB 7.4.2, SB 7.4.9-12, SB 7.6.29-30, SB 7.8.47, SB 7.8.51, SB 7.8.53, SB 7.10.26
SB 7.10.52, SB 8.1.1, SB 8.1.31, SB 8.3.8-9, SB 8.3.22-24, SB 8.5.11-12, SB 8.7.21, SB 8.14.1
SB 8.15.1-2, SB 8.17.25, SB 8.22.21, SB 8.24.1, SB 9.1.1, SB 9.1.28, SB 9.4.14, SB 9.9.19
SB 9.11.4, SB 9.11.24, SB 9.13.11, SB 9.14.19, SB 9.15.16, SB 9.18.5, SB 9.20.13, SB 10.1.1
SB 10.4.14, SB 10.30.37, SB 10.41.28, SB 10.53.10, SB 10.54.17, SB 10.89.53, SB 11.4.7, SB 11.29.7
SB 11.29.8, SB 12.6.67, SB 12.6.70
```
</details>
