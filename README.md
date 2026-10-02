# Postcard Plotter — handwriting G-code in the browser

Type a message and the recipient's address, choose a single-stroke handwriting
font, see both laid out on a real-size postcard, download one `.gcode` for
Candle.

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

`.claude/launch.json` holds the same `http.server` command so the Claude
desktop app's Browser pane can start the site with one click.

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

```bash
python tests/test_address.py
```

Checks the address block: a blank address leaves the G-code byte-identical,
a typed one lands inside the address area after the message, lines are never
re-wrapped, and fit mode reserves room for the configured number of lines.
Needs only `lib/`, so it runs on a fresh clone.

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
2. Type the address, **one address line per row**, exactly as it should
   appear on the card. Address lines are never re-wrapped. Leave it empty to
   plot the message only (or leave the message empty to pre-address a batch).
3. Pick a font. *EMS Allure* is the flowing formal cursive used for the
   ministry postcards.
4. Choose **Fit the writing area** and set the area's width and height; the
   letter size is chosen for you (this disables the letter-height and wrap
   fields). Or choose **Fixed letter size** to drive it yourself, in which case
   the writing area becomes a guide that warns you when text overflows.
5. The address has the same two modes. **Fit the address area** picks the
   largest size at which the longest line fits the width *and* at least
   "Room for N lines" lines fit the height (default 6, a full UK address:
   name, house and street, locality, post town, county, postcode). Reserving
   the room means a 3-line address is not blown up to fill the box, so every
   card in a batch gets the same address size.
6. Check the preview, then **Download .gcode**. Message and address are in
   the same file, message first.
7. In Candle: jog the pen to the corner marked `0,0` in the preview — by
   default the bottom-left of the writing area — zero X and Y, and send.
   The address coordinates are relative to that same zero.

The card preview is a sketch, not a scan of your stock: the centre divider is
where the message half ends, but the stamp box is a guess. The address area's
position and size (under *The card* and *Address*) are the things to adjust
to match your actual cards.

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
