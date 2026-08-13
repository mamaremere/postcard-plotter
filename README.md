# Postcard Plotter — handwriting G-code in the browser

Type a message, choose a single-stroke handwriting font, see it laid out on a
real-size postcard, download `.gcode` for Candle.

It is a **static site**: the Python from [`../text2gcode`](../text2gcode) runs
inside your browser through [Pyodide](https://pyodide.org). There is no server
and no build step — which means the same code that has been driving the
plotter produces the web output, byte for byte (see *Tests*).

**Your message never leaves your device.** No text is uploaded, no files are
written anywhere: previews are strings in memory, downloads are Blobs whose
object URLs are released straight after saving, and an uploaded font lives
only until you close the tab.

## Running it locally

```bash
python -m http.server 8765
```

then open <http://127.0.0.1:8765>. First load fetches the ~11 MB Pyodide
runtime from jsDelivr; after that the browser caches it.

## Publishing on GitHub Pages

The repo root *is* the site, so no build step and no workflow file are needed.

1. Create a **public** repository on GitHub (Pages needs public on free plans).
2. Push this folder to it.
3. Repository **Settings → Pages → Source: Deploy from a branch**, branch
   `main`, folder `/ (root)`, Save.
4. A minute later the site is live at
   `https://<your-user>.github.io/<repo>/`.

Cloudflare Pages and Netlify also work — point them at this folder, no build
command, publish directory `.`.

## Editing

| You changed… | Do this |
|---|---|
| `index.html`, `app.js`, `style.css` | nothing — reload the page |
| `webapi.py`, or anything in `../text2gcode` | `python build.py`, then commit `bundle.zip` |

`bundle.zip` is a build artifact (library + fonts + `webapi.py`) that is
committed on purpose, because GitHub Pages cannot run `build.py` for you.
`../text2gcode` remains the single source of truth; nothing is duplicated by
hand.

## Tests

```bash
python tests/test_fidelity.py
```

Asserts that `webapi.generate()` reproduces `../text2gcode/out/postcard_65x80.gcode`
**exactly**. If a change to the layout, fitting, or smoothing code ever alters
the output, this fails loudly instead of you discovering it on paper.

## How the pieces fit

```
index.html / style.css / app.js   the page: controls, card preview, downloads
webapi.py                         thin JSON adapter (the only new Python)
bundle.zip                        text2gcode.py + hersheydata.py + fonts/ + webapi.py
build.py                          rebuilds bundle.zip from ../text2gcode
tests/test_fidelity.py            web output == CLI output
```

`app.js` never touches Python objects: every call is a JSON string in and a
JSON string out. Geometry stays in the tested Python; the card template,
rulers and zero marker are drawn in JavaScript around the ink path.

## Using it

1. Type the message. **One paragraph per line** — don't press Enter at the end
   of each line; the layout wraps for you and packs tighter than hand-wrapping.
   A blank line starts a new paragraph.
2. Pick a font. *EMS Allure* is the flowing formal cursive used for the
   ministry postcards.
3. Choose **Fit the writing area** and set the area's width and height; the
   letter size is chosen for you (this disables the letter-height and wrap
   fields). Or choose **Fixed letter size** to drive it yourself, in which case
   the writing area becomes a guide that warns you when text overflows.
4. Check the preview, then **Download .gcode**.
5. In Candle: jog the pen to the corner marked `0,0` in the preview — by
   default the bottom-left of the writing area — zero X and Y, and send.

Below about 3 mm capitals use a 0.2–0.3 mm gel pen or fineliner; a thicker
ballpoint closes up the loops of cursive letters. Test on scrap paper cut to
the same size first.

## Fonts

Built in: the 9 **EMS single-line** fonts (SIL Open Font License) and a
selection of the **Hershey** set (Dr. A. V. Hershey, U.S. National Bureau of
Standards; data format by James Hurt, Cognition Inc.).

You can upload more — **single-line SVG fonts only**, such as those in the
Inkscape extensions repository (`gitlab.com/inkscape/extensions`, `svg_fonts/`).
Ordinary TrueType/OpenType fonts are *outline* fonts: each letter is a closed
contour, so a pen traces around it and draws hollow double letters. If you
upload one, the app detects the closed loops and warns you.
