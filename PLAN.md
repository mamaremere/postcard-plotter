# Plan — text2gcode on the web

Goal: author postcard/letter G-code from any device (phone, tablet, someone
else's laptop), without installing Python. Type text, pick a font, see it laid
out on a real-size postcard, download the `.gcode`, load it in Candle.

Status: **plan approved — not yet built.**

### Decisions (confirmed 2026-08-13)

| Question | Decision |
|---|---|
| Architecture | **Browser-only (Pyodide)** — static site, no server |
| Card layout | Writing area on the **left / message half** of the 150 × 105 card |
| Audience | **You + others in the ministry** → milestone 6 includes a friendly first run and shareable settings links |
| Keep the CLI | Yes — the web app imports the same module, so both stay in sync |

---

## 1. Architecture (confirmed): run the Python *in the browser*

The surprising-but-correct answer: **there is no server.** The page ships the
existing `text2gcode.py` unchanged and runs it inside the browser via
[Pyodide](https://pyodide.org) (CPython compiled to WebAssembly). The site is
plain static files — hostable free, forever, on GitHub Pages / Cloudflare
Pages / Netlify.

### Why this over a normal Python server

Measured on the real postcard job (70 words, EMS Allure, auto-fit 65×80):

| | full auto-fit | single layout | assets |
|---|---|---|---|
| measured | **129 ms** | 4 ms | 950 KB (fonts + Hershey data + script) |

The compute is trivial, so a server buys us nothing — it only adds failure
modes:

| | **A. Browser (Pyodide)** ← recommended | B. Server (FastAPI on Render/HF) | C. Rewrite in JavaScript |
|---|---|---|---|
| Hosting | static, free forever | free tier, policy can change | static, free forever |
| Wake-up delay | ~4–6 s **first load only**, then instant | **~60 s** after 15 min idle (Render free) | instant |
| Payload | ~11 MB once, browser-cached | tiny | ~150 KB |
| Uses our tested code | **yes, byte-identical** | yes | **no — full reimplementation** |
| Donor names / letter text | **never leaves the device** | uploaded to a third party | never leaves device |
| Files to clean up | **none — nothing is written** | temp files + uploads to manage | none |
| Works offline | yes (after first load) | no | yes |
| Ongoing maintenance | vendored assets | server, deps, platform limits | two codebases in sync |

The decisive points:

1. **A 60-second cold start is unusable** for a tool you open in bursts to
   write one postcard. Render's free tier spins down after 15 minutes idle;
   PythonAnywhere's free tier caps you at 100 CPU-seconds/day.
2. **Same code, no divergence.** The G-code you've already validated on the
   plotter comes out of the same functions. Option C would mean re-deriving
   the spline/fit/layout maths in JS and hoping it matches.
3. **Privacy.** The letters contain donor names. Client-side means the text
   never touches anyone's server, which also sidesteps GDPR questions
   entirely for a ministry mailing.

The only real cost is the ~11 MB Pyodide runtime on first visit (~4–6 s on
wifi, cached afterwards, and a service worker makes it fully offline). We
mitigate with a progress bar, and it happens once per device.

`text2gcode.py` is already compatible: it imports **only stdlib**
(`math`, `os`, `re`, `sys`, `unicodedata`, `xml.etree`) — all present in
Pyodide — and its library functions are pure (only `main()` touches disk).

**Fallback:** if you later want a link you can hand to a non-technical
colleague without an 11 MB load, option B is a ~100-line FastAPI wrapper
around the same module. The plan keeps that door open by isolating all
browser-specific code in `app.js`.

---

## 2. What you see on screen

Single page, two columns on desktop, stacked on mobile.

```
┌─────────────────────────┬───────────────────────────────┐
│ TEXT                    │  PREVIEW                      │
│ ┌─────────────────────┐ │  ┌─────────────────────────┐  │
│ │ Dear Ziggy,         │ │  │ ╔═══════════════════╗   │  │
│ │                     │ │  │ ║ 150 × 105 mm card ║   │  │
│ │ Thank you for your  │ │  │ ║ ┌───────┐         ║   │  │
│ │ faithful...         │ │  │ ║ │ text  │ address ║   │  │
│ └─────────────────────┘ │  │ ║ └───────┘  lines  ║   │  │
│                         │  │ ╚═══════════════════╝   │  │
│ FONT   [EMS Allure  ▾]  │  └─────────────────────────┘  │
│        [ Upload font… ] │  ⬤ machine zero               │
│                         │                               │
│ SIZE                    │  64.7 × 75.8 mm · 447 strokes │
│  ◉ Fit to writing area  │  3.3 m ink · ≈ 8.0 min        │
│    W [65] × H [80] mm   │                               │
│    → auto: 2.88 mm caps │  [ Download .gcode ]          │
│  ○ Fixed letter height  │  [ Download preview .svg ]    │
│    height   [—] mm      │                               │
│    wrap at  [—] mm      │                               │
└─────────────────────────┴───────────────────────────────┘
```

### The mode switch you asked for

A radio pair drives which inputs are live:

| Mode | Enabled | Disabled (greyed, with reason on hover) |
|---|---|---|
| **Fit to writing area** | box `W × H` | `height`, `wrap at` — replaced by a read-only “auto: 2.88 mm caps” readout |
| **Fixed letter height** | `height`, `wrap at` | box `W × H` stays editable but becomes *guide only*; if the text spills outside it the box turns amber and the stats line says “overflows writing area by 12 mm” |

So the writing-area rectangle always exists (it's a real thing on your card);
in fit mode it *drives* the size, in fixed mode it only *checks* it.

### All controls

- **Text** — textarea, one paragraph per line (blank line = paragraph break).
  A hint reminds you not to hand-wrap, since the wrapper packs tighter.
- **Font** — grouped dropdown: *Smooth (EMS)* / *Classic (Hershey)* /
  *Uploaded*. Plus the `Upload font…` button (§4).
- **Size** — the mode switch above.
- **Layout** — align (left/center/right), line spacing, paragraph gap,
  letter spacing.
- **Placement** — where the writing area sits on the card (X/Y from a card
  corner), and **“machine zero is at:”** → *writing-area corner* (default,
  matches how you work now) or *card corner*. The preview marks the chosen
  zero, and the G-code offsets to match.
- **Pen & machine** (collapsed “Advanced”) — draw feed, travel feed, pen
  delay, power S, pen-up/pen-down commands, return-home toggle.
- **Smoothing** (collapsed) — on/off, step, corner angle. Auto-hidden for
  EMS fonts, which are already curves.

### Quality-of-life

- **Presets** in `localStorage`: “postcard portrait 65×80”, “landscape”, etc.
- **Shareable settings link** — parameters encoded in the URL hash, so you can
  mail yourself a configured link. No server needed. Text excluded by default
  (it's private and long); opt-in checkbox to include it.
- Live preview, debounced ~250 ms. At 129 ms worst case it feels instant.

---

## 3. Preview: the postcard template

The preview is an SVG drawn at true scale (1 unit = 1 mm) showing, back to
front:

1. **Card** — 150 × 105 mm, rounded corners, subtle paper fill and drop
   shadow. Orientation toggle (landscape/portrait) and editable dimensions,
   defaulting to 150 × 105.
2. **Optional postcard furniture** — a faint centre divider at x = 75 mm, a
   stamp box (top-right) and address ruled lines on the right half, so you can
   see the message area in context. Toggleable, never plotted.
3. **Writing-area rectangle** — dashed, the box from §2. **Default placement:
   the message half**, i.e. 65 × 80 mm at x = 6 mm, y = 12.5 mm from the card's
   bottom-left. That leaves a 6 mm left margin, a 4 mm gap before the centre
   divider, and centres the block vertically.
4. **The ink** — the actual polylines, stroked at ~0.3 mm to approximate a
   fineliner, so the preview honestly shows whether small cursive will clog.
5. **Machine-zero marker** — red crosshair + label, at whichever corner you
   selected.
6. **Ruler ticks** along two edges (10 mm), for sanity-checking against the
   real card.

Rendering split: **Python returns the ink as one compact SVG path string**
(`M x y L x y …`) plus the stats; **JavaScript composes the card template
around it.** That keeps the geometry in the tested Python and the presentation
in HTML/CSS where it's easy to iterate — and the payload stays small
(a full postcard's ink path is ~100 KB of text, not megabytes of JSON).

---

## 4. Fonts

**Built in** — the 9 EMS single-line fonts + the Hershey set already on disk,
shipped as a bundle with the site (~950 KB, one fetch).

**Upload** — the file is read with the browser's `FileReader` into a string,
handed to Python, and registered in memory. It is **never written to any
server** (there is none) and vanishes when the tab closes; a “Remove” button
clears it immediately.

Accepted format: **SVG single-line fonts** (`<font>` / `<glyph d="…">`) — the
format the plotter community uses, and what the EMS/Hershey sets already are.
More can be downloaded from the Inkscape extensions repo
(`gitlab.com/inkscape/extensions`, `svg_fonts/`).

**Outline-font guard.** This directly addresses the problem you started with:
if an uploaded font's glyphs are mostly *closed* paths (lots of `Z`, or each
glyph doubling back on itself), we detect it and warn:

> “This looks like an **outline** font — letters will plot as hollow
> double contours. Single-line fonts draw each stroke once.”

Requires a small addition to `text2gcode.py`: `SvgFont.from_string()`
alongside the existing file-based constructor. TrueType/OTF upload is
deliberately **not** supported — those are outline fonts by definition and
would recreate the original hollow-letter problem.

---

## 5. Files & cleanup

You asked how to clean up generated files and temporary uploaded fonts. The
best answer is to make the question disappear:

### Nothing is ever written to a disk

| Thing | Where it lives | How it goes away |
|---|---|---|
| Preview SVG | a JavaScript string | garbage-collected |
| G-code | a `Blob` built on click | `URL.revokeObjectURL()` immediately after the save dialog |
| Uploaded font | JS string + Pyodide's in-memory filesystem | “Remove” button, or closing the tab |
| Pyodide runtime | browser HTTP cache | normal cache eviction; “clear site data” |

The only file that persists anywhere is the `.gcode` **you** deliberately save
to your Downloads folder. There is no server directory to sweep, no cron job,
no orphaned temp files, and no upload quota to police.

### If you ever switch to the server fallback (option B)

Then the discipline matters, so the rules would be:

- Generate into `io.BytesIO` and return via `StreamingResponse` — **never**
  write a file and then serve it.
- If a real file is unavoidable, `tempfile.TemporaryDirectory()` as a context
  manager, so it's removed even on exception. Never a fixed `uploads/` dir.
- Uploads: cap size (~2 MB), cap text length, validate it parses as an SVG
  font *before* using it, ignore the client-supplied filename entirely
  (path-traversal), discard after the response.
- Belt-and-braces sweeper deleting anything older than ~15 min, in case a
  process was killed mid-request.
- Basic rate limiting, since the endpoint does real CPU work.

### Housekeeping on your laptop (independent of all this)

`text2gcode\` currently holds **22 generated files, 2.6 MB** — samplers,
previews, postcard variants — mixed in with 950 KB of actual source. Suggested:

- Default outputs to an `out\` subfolder (a small change to the script's
  `--out` default), so generated and source never mix again.
- Add a `clean.py` (or one-line PowerShell) that empties `out\`.
- If this ever goes into git: `.gitignore` with `out/`, `*.gcode`,
  `*.preview.svg` — commit the fonts and scripts, never the output.

I'd keep `hello_allure`, the two samplers and the four postcard files as
reference, and clear the rest.

---

## 6. Repo layout & the Python↔JS contract

```
text2gcode-web/
  index.html          markup + inlined critical CSS
  app.js              UI state, preview composition, downloads
  style.css
  webapi.py           thin adapter, the ONLY new Python (~80 lines)
  build.py            zips ../text2gcode into bundle.zip
  bundle.zip          text2gcode.py + hersheydata.py + fonts/  (generated)
  sw.js               service worker → offline + installable
  tests/golden/       reference .gcode for the fidelity test
  README.md
```

`webapi.py` exposes three functions, all JSON in / JSON out, so `app.js` never
touches Python objects:

| call | returns |
|---|---|
| `list_fonts()` | `[{id, label, group, kind}]` |
| `preview(params)` | `{ink_path_d, height_used, info{width,height,strokes,ink_mm,travel_mm,minutes,dropped}, warnings[]}` |
| `generate(params)` | `{gcode, filename, info}` |
| `add_font(name, svg_text)` | `{id, label, warnings[]}` |

Preview and generate are separate so live typing never pays to serialise
155 KB of G-code.

**Fidelity test (important):** `tests/golden/` holds `postcard_65x80.gcode`
produced by the CLI you've already plotted from. A test asserts the web path
produces it **byte-for-byte**. If a refactor ever changes the output, that
test fails loudly rather than you discovering it on paper.

---

## 7. Hosting

Static files, so the choices are all genuinely free with no sleep:

1. **Cloudflare Pages** — recommended. Drag-and-drop or git; global CDN;
   generous free tier; works with a private repo.
2. **GitHub Pages** — simplest if the repo is public (Pages from a private
   repo needs a paid plan). Push to `main`, enable Pages, done.
3. **Netlify** — equivalent to Cloudflare, also drag-and-drop.

All three serve the ~11 MB Pyodide bundle fine, or we let jsDelivr's CDN serve
Pyodide and host only our ~1 MB. With the service worker it becomes an
installable app — “Add to Home Screen” on your phone, and it then works with
no connection at all (useful if you plot somewhere without wifi).

---

## 8. Build order

| # | Milestone | Proves |
|---|---|---|
| 1 | Static page boots Pyodide, loads the bundle, lists fonts | the whole risky part works |
| 2 | Text + font + fixed height → ink path → rendered on the card | core loop |
| 3 | Fit mode + the enable/disable logic + stats line | your main requirement |
| 4 | Download `.gcode` (+ golden fidelity test) | it's actually usable |
| 5 | Font upload + outline-font warning | the upload requirement |
| 6 | Presets, URL sharing, mobile layout, service worker, first-run help | usable by colleagues |
| 7 | Deploy + README | done |

Milestones 1–4 are the useful core; 5–7 can follow later.

Because others in the ministry will use it, milestone 6 also gets: sensible
defaults on first load (a sample letter already in the box so the tool
explains itself), plain-language labels with “what does this do?” tooltips
instead of CLI jargon, and a one-click **“Copy settings link”** so you can
send a colleague a pre-configured card to type into.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| 11 MB first load on mobile data | progress bar; one-time; service worker caches it; document it |
| iOS Safari memory limits with WASM | test early on your phone (milestone 1); fallback is option B |
| Huge text + tiny font → slow preview | debounce; cap text length; stats warn before render |
| Web output drifts from the CLI | golden byte-comparison test in CI |
| Pyodide version churn | pin the version and vendor it, don't float on `latest` |

---

## 10. Still to decide (can wait until we build)

None of these block starting; each has a sensible default I'll use unless you
say otherwise.

1. **Site name / URL** — e.g. `plotter.pages.dev` or a custom domain.
   Default: whatever Cloudflare Pages assigns.
2. **Self-host Pyodide or use the jsDelivr CDN?** Default: vendor it, so the
   site keeps working if the CDN or its version policy changes.
3. **Which built-in fonts to show first.** Default: EMS Allure, since that's
   what the postcards use; Hershey grouped below as “classic”.
4. **Card presets beyond 150 × 105** — A6, A5, business card? Default: ship
   150 × 105 plus a free-size option, add more if you hit them.
