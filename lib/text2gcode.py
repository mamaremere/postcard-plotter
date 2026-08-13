#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
text2gcode.py - single-stroke ("handwriting") text -> G-code for the AX5 pen plotter.

Renders text with Hershey single-line vector fonts (the same data behind
Inkscape's "Hershey Text" extension) and writes G-code in the exact dialect
produced by the Doesbot "Gcode Generation Tool" (M03 = pen down, M05 = pen up),
ready to load straight into Candle.

Acknowledgement (required by the Hershey font license):
  - The Hershey Fonts were originally created by Dr. A. V. Hershey while
    working at the U. S. National Bureau of Standards.
  - The format of the font data (hersheydata.py) was originally created by
    James Hurt, Cognition, Inc.

Examples:
  python text2gcode.py "Hello world" -o hello.gcode
  python text2gcode.py "Dear Ana,\nsee you soon!" --font scripts --height 12 --align center
  python text2gcode.py --file letter.txt --max-width 180 --origin 15,15
  python text2gcode.py --list-fonts
"""

import argparse
import math
import os
import re
import sys
import unicodedata
from xml.etree import ElementTree

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import hersheydata  # noqa: E402  (font data file sitting next to this script)

# ---------------------------------------------------------------- fonts

FONT_NOTES = {
    "scripts":   "cursive script, single stroke  <-- best 'handwriting' look",
    "cursive":   "cursive, single stroke",
    "scriptc":   "cursive script, heavier (double stroke)",
    "futural":   "sans-serif print, single stroke  <-- clean block handwriting",
    "futuram":   "sans-serif bold (double stroke)",
    "timesr":    "serif roman (double stroke)",
    "timesi":    "serif italic (double stroke)",
    "timesrb":   "serif bold (double stroke)",
    "timesib":   "serif bold italic (double stroke)",
    "gothiceng": "blackletter / old English",
    "gothicger": "blackletter, German style",
    "gothicita": "blackletter, Italian style",
    "greek":     "Greek alphabet",
    "cyrillic":  "Cyrillic alphabet",
    "timesg":    "Greek serif",
    "japanese":  "Japanese glyphs",
    "astrology": "astrology symbols",
    "markers":   "marker symbols",
    "mathlow":   "math symbols (lowercase positions)",
    "mathupp":   "math symbols (uppercase positions)",
    "meteorology": "meteorology symbols",
    "music":     "music symbols",
    "symbolic":  "misc symbols",
}

# Text fonts first, symbol fonts later, when listing.
_TEXT_FONTS = ["scripts", "cursive", "scriptc", "futural", "futuram",
               "timesr", "timesi", "timesrb", "timesib",
               "gothiceng", "gothicger", "gothicita", "greek", "cyrillic", "timesg"]


def available_fonts():
    names = []
    for name in dir(hersheydata):
        if name.startswith("_"):
            continue
        val = getattr(hersheydata, name)
        if isinstance(val, list) and len(val) >= 90 and all(isinstance(g, str) for g in val[:5]):
            names.append(name)
    ordered = [n for n in _TEXT_FONTS if n in names]
    ordered += sorted(n for n in names if n not in ordered)
    return ordered


def get_font(name):
    if not hasattr(hersheydata, name):
        raise SystemExit("Unknown font '%s'. Run with --list-fonts to see choices." % name)
    return getattr(hersheydata, name)

# ---------------------------------------------------------------- glyph parsing

def parse_glyph(gstr):
    """Return (left, right, strokes). Strokes are lists of (x, y) in font units.

    Glyph format: "<left> <right> M x y L x y L x y M x y ..." - SVG-ish absolute
    coords, y grows DOWNWARD, baseline at y = +9 for the standard Hershey fonts.
    """
    toks = gstr.split()
    left, right = float(toks[0]), float(toks[1])
    strokes, cur = [], None
    i = 2
    while i < len(toks):
        t = toks[i]
        if t == "M":
            cur = []
            strokes.append(cur)
            i += 1
        elif t == "L":
            i += 1
        else:
            x = float(toks[i]); y = float(toks[i + 1])
            i += 2
            if cur is None:          # data without a leading M (defensive)
                cur = []
                strokes.append(cur)
            cur.append((x, y))
    return left, right, [s for s in strokes if s]


def font_metrics(font):
    """Measure baseline / cap height / descender straight from the glyph data."""
    def ys_of(ch):
        idx = ord(ch) - 32
        if 0 <= idx < len(font):
            _, _, strokes = parse_glyph(font[idx])
            return [y for s in strokes for (_, y) in s]
        return []

    h_ys = ys_of("H") or ys_of("A") or [-12.0, 9.0]
    baseline = max(h_ys)
    cap_h = baseline - min(h_ys)
    if cap_h <= 0:
        baseline, cap_h = 9.0, 21.0
    descender = 0.0
    for ch in "gjpqy":
        ys = ys_of(ch)
        if ys:
            descender = max(descender, max(ys) - baseline)
    return baseline, cap_h, descender

# ---------------------------------------------------------------- font objects
#
# Both font kinds are exposed through the same tiny API:
#   .name, .kind, .cap (capital height, font units),
#   .line_height (natural line pitch, font units),
#   .has(ch), .advance(ch), .strokes(ch, tol) -> polylines in font units,
#   y UP, baseline at y=0, glyph starting at x=0.

# Characters that reach highest and lowest - what actually decides whether two
# consecutive lines collide.
_LH_SAMPLE = "AXBEhklt bdfgjpqy"


def _measure_line_height(font):
    """The font's natural line pitch: the real ink span from the top of an
    ascender to the bottom of a descender, in font units.

    Cap height alone is not enough - a formal script reaches 2.3x its cap
    height once loops are counted, while a plain sans reaches only 1.4x, so
    spacing lines by cap height overlaps some fonts and not others.
    """
    tol = max(font.cap / 50.0, 0.01)
    ys = []
    for ch in _LH_SAMPLE:
        if font.has(ch):
            for s in font.strokes(ch, tol):
                ys.extend(y for (_, y) in s)
    if not ys:
        return font.cap * 1.6
    return max(ys) - min(ys)


class HersheyFont:
    kind = "hershey"

    def __init__(self, name):
        data = get_font(name)
        self.name = name
        baseline, cap_h, _ = font_metrics(data)
        self.cap = cap_h
        self.glyphs = {}
        for i, gstr in enumerate(data):
            ch = chr(32 + i)
            left, right, strokes = parse_glyph(gstr)
            up = [[(x - left, baseline - y) for (x, y) in s] for s in strokes]
            self.glyphs[ch] = (right - left, up)
        self.line_height = _measure_line_height(self)

    def has(self, ch):
        return ch in self.glyphs

    def advance(self, ch):
        return self.glyphs[ch][0]

    def strokes(self, ch, tol=None):
        return self.glyphs[ch][1]


class SvgFont:
    """Single-line SVG font (<font>/<glyph d=...>), e.g. the EMS fonts.

    SVG fonts use em coordinates: y grows UP and the baseline is y=0, which is
    exactly our internal convention. Curves are flattened on demand with a
    deviation tolerance given in font units.
    """
    kind = "svg"

    @classmethod
    def from_string(cls, svg_text, name=None):
        """Build a font from SVG markup held in memory (used by the web app,
        so an uploaded font never has to touch a disk)."""
        self = cls.__new__(cls)
        self._init_from_root(ElementTree.fromstring(svg_text), name or "uploaded")
        return self

    def __init__(self, path):
        self._init_from_root(ElementTree.parse(path).getroot(),
                             os.path.splitext(os.path.basename(path))[0])

    def _init_from_root(self, root, fallback_name):
        def local(tag):
            return tag.rsplit("}", 1)[-1]

        font_el = next((el for el in root.iter() if local(el.tag) == "font"), None)
        if font_el is None:
            raise ValueError("no <font> element - this is not an SVG font file")
        face = next((el for el in font_el.iter() if local(el.tag) == "font-face"), None)
        fam = face.get("font-family") if face is not None else None
        self.name = fam or fallback_name
        self.upem = float(face.get("units-per-em", 1000)) if face is not None else 1000.0
        self.default_adv = float(font_el.get("horiz-adv-x", self.upem / 2.0))
        self.glyphs = {}
        for g in font_el.iter():
            if local(g.tag) != "glyph":
                continue
            u = g.get("unicode")
            if u is None or len(u) != 1:
                continue
            adv = float(g.get("horiz-adv-x", self.default_adv))
            self.glyphs[u] = (adv, g.get("d"))
        if " " not in self.glyphs:
            self.glyphs[" "] = (self.default_adv, None)
        cap = float(face.get("cap-height", 0)) if face is not None else 0.0
        self._cache = {}
        self.cap = cap or self._measure_cap()
        self.line_height = _measure_line_height(self)

    def _measure_cap(self):
        for ch in "HEIT":
            d = self.glyphs.get(ch, (0, None))[1]
            if d:
                ys = [y for s in parse_svg_path(d, 1.0) for (_, y) in s]
                if ys:
                    return max(ys)
        return 0.7 * self.upem

    def has(self, ch):
        return ch in self.glyphs

    def advance(self, ch):
        return self.glyphs[ch][0]

    def strokes(self, ch, tol=1.0):
        key = (ch, round(tol, 6))
        if key not in self._cache:
            d = self.glyphs[ch][1]
            self._cache[key] = parse_svg_path(d, tol) if d else []
        return self._cache[key]


_PATH_TOKEN = re.compile(r"[MmLlCcZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def _flatten_cubic(p0, p1, p2, p3, tol, out, depth=0):
    dx, dy = p3[0] - p0[0], p3[1] - p0[1]
    chord = math.hypot(dx, dy) or 1e-12
    d1 = abs((p1[0] - p0[0]) * dy - (p1[1] - p0[1]) * dx) / chord
    d2 = abs((p2[0] - p0[0]) * dy - (p2[1] - p0[1]) * dx) / chord
    if depth >= 16 or (d1 + d2) <= tol:
        out.append(p3)
        return
    mid = lambda a, b: ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    m01, m12, m23 = mid(p0, p1), mid(p1, p2), mid(p2, p3)
    m012, m123 = mid(m01, m12), mid(m12, m23)
    m = mid(m012, m123)
    _flatten_cubic(p0, m01, m012, m, tol, out, depth + 1)
    _flatten_cubic(m, m123, m23, p3, tol, out, depth + 1)


def parse_svg_path(d, tol):
    """Parse an SVG path (M/L/C/Z, absolute or relative) into polylines."""
    toks = _PATH_TOKEN.findall(d)
    strokes, cur = [], None
    cx = cy = sx = sy = 0.0
    cmd = None
    i = 0

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        if toks[i] in "MmLlCcZz":
            cmd = toks[i]
            i += 1
        if cmd in "Mm":
            x, y = num(), num()
            if cmd == "m":
                x += cx
                y += cy
            cur = [(x, y)]
            strokes.append(cur)
            cx, cy, sx, sy = x, y, x, y
            cmd = "L" if cmd == "M" else "l"   # implicit lineto continuation
        elif cmd in "Ll":
            x, y = num(), num()
            if cmd == "l":
                x += cx
                y += cy
            cur.append((x, y))
            cx, cy = x, y
        elif cmd in "Cc":
            x1, y1, x2, y2, x, y = num(), num(), num(), num(), num(), num()
            if cmd == "c":
                x1 += cx; y1 += cy; x2 += cx; y2 += cy; x += cx; y += cy
            _flatten_cubic((cx, cy), (x1, y1), (x2, y2), (x, y), tol, cur)
            cx, cy = x, y
        elif cmd in "Zz":
            if cur and (abs(cx - sx) > 1e-9 or abs(cy - sy) > 1e-9):
                cur.append((sx, sy))
                cx, cy = sx, sy
        else:
            raise ValueError("Unsupported SVG path command: %r" % cmd)
    return [s for s in strokes if s]


def _normkey(s):
    return "".join(c for c in s.lower() if c.isalnum())


def svg_font_dir():
    return os.path.join(_HERE, "fonts")


def list_svg_fonts():
    d = svg_font_dir()
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if f.lower().endswith(".svg"))


def resolve_font(name):
    """Accept a Hershey font name, an SVG font file name/path, or a loose
    match against the fonts/ folder (e.g. 'ems-allure' -> EMSAllure.svg)."""
    if isinstance(name, (HersheyFont, SvgFont)):
        return name
    if name.lower().endswith(".svg"):
        for cand in (name, os.path.join(svg_font_dir(), name)):
            if os.path.exists(cand):
                return SvgFont(cand)
        raise SystemExit("SVG font file not found: %s" % name)
    if hasattr(hersheydata, name):
        return HersheyFont(name)
    key = _normkey(name)
    for f in list_svg_fonts():
        if _normkey(os.path.splitext(f)[0]) == key:
            return SvgFont(os.path.join(svg_font_dir(), f))
    raise SystemExit("Unknown font '%s'. Run with --list-fonts to see choices." % name)

# ---------------------------------------------------------------- text handling

_CHAR_MAP = {
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "–": "-", "—": "-", "−": "-",
    "…": "...", " ": " ", "\t": "    ",
}


def normalize_text(text, font):
    """Map text onto the characters the font actually has; strip accents."""
    out = []
    dropped = set()
    for ch in text:
        if ch == "\n":
            out.append(ch)
            continue
        ch = _CHAR_MAP.get(ch, ch)
        for c in ch:
            if font.has(c):
                out.append(c)
                continue
            # try removing diacritics (ă -> a, ș -> s, é -> e, ...)
            base = unicodedata.normalize("NFKD", c)
            base = "".join(b for b in base if not unicodedata.combining(b))
            if base and font.has(base[0]):
                out.append(base[0])
            else:
                dropped.add(c)
                out.append(" ")
    return "".join(out), dropped


def advance_of(ch, font, extra_units):
    return font.advance(ch) + extra_units


def measure(line, font, extra_units):
    return sum(advance_of(ch, font, extra_units) for ch in line)


def wrap_line(line, font, extra_units, max_units):
    """Greedy word wrap; returns a list of lines."""
    words = line.split(" ")
    space_w = advance_of(" ", font, extra_units)
    lines, cur, cur_w = [], "", 0.0
    for w in words:
        w_w = measure(w, font, extra_units)
        if not cur:
            cur, cur_w = w, w_w
        elif cur_w + space_w + w_w <= max_units:
            cur += " " + w
            cur_w += space_w + w_w
        else:
            lines.append(cur)
            cur, cur_w = w, w_w
    lines.append(cur)
    return lines

# ---------------------------------------------------------------- layout

def text_to_polylines(text, fontname="scripts", height=10.0, line_spacing=1.0,
                      char_spacing=0.0, align="left", max_width=None,
                      origin=(10.0, 10.0), smooth=True, smooth_step=0.25,
                      corner_angle=75.0, paragraph_gap=1.0):
    """Lay text out and return (polylines, info).

    polylines: list of [(x, y), ...] in mm, machine coords (X right, Y up,
    absolute, positive). The whole block is shifted so its bottom-left corner
    sits at `origin`.
    """
    font = resolve_font(fontname)
    scale = float(height) / font.cap          # mm per font unit
    extra_units = char_spacing / scale        # extra tracking, font units
    flat_tol = 0.02 / scale                   # flatten curves to ~0.02 mm

    text, dropped = normalize_text(text, font)
    raw_lines = text.split("\n")
    lines = []
    for ln in raw_lines:
        if max_width and ln.strip():
            lines.extend(wrap_line(ln, font, extra_units, max_width / scale))
        else:
            lines.append(ln)

    # Line pitch follows the font's real ascender-to-descender span, so script
    # fonts with deep loops get the room they need and plain fonts do not get
    # needlessly airy. line_spacing 1.0 = lines just clear each other.
    line_h = font.line_height * scale * line_spacing
    widths = [measure(ln, font, extra_units) * scale for ln in lines]
    block_w = max(widths) if widths else 0.0

    polys = []
    y_cursor = 0.0                            # first line on top
    for i, ln in enumerate(lines):
        if not ln.strip():
            y_cursor -= line_h * paragraph_gap   # blank line = paragraph gap
            continue
        if align == "center":
            x_off = (block_w - widths[i]) / 2.0
        elif align == "right":
            x_off = block_w - widths[i]
        else:
            x_off = 0.0
        base_y = y_cursor
        cursor = 0.0                          # font units
        for ch in ln:
            for s in font.strokes(ch, flat_tol):
                pts = [(x_off + (cursor + gx) * scale,
                        base_y + gy * scale) for (gx, gy) in s]
                polys.append(pts)
            cursor += font.advance(ch) + extra_units
        y_cursor -= line_h

    if not polys:
        raise SystemExit("Nothing to draw - the text contains no drawable characters.")

    polys = merge_polylines(polys)
    if smooth and font.kind == "hershey":
        # Hershey data is segmented; spline it. SVG fonts are already curves.
        polys = [smooth_polyline(p, smooth_step, corner_angle) for p in polys]

    # shift block so bottom-left of the ink sits at `origin`
    min_x = min(p[0] for poly in polys for p in poly)
    min_y = min(p[1] for poly in polys for p in poly)
    dx, dy = origin[0] - min_x, origin[1] - min_y
    polys = [[(x + dx, y + dy) for (x, y) in poly] for poly in polys]

    max_x = max(p[0] for poly in polys for p in poly)
    max_y = max(p[1] for poly in polys for p in poly)
    info = {
        "font": font.name, "lines": len(lines), "dropped": dropped,
        "bbox": (origin[0], origin[1], max_x, max_y),
        "width": max_x - origin[0], "height": max_y - origin[1],
    }
    return polys, info


def fit_text(text, fontname, box_w, box_h, line_spacing=1.0, char_spacing=0.0,
             align="left", paragraph_gap=1.0, smooth=True, smooth_step=0.25,
             corner_angle=75.0):
    """Find the largest cap height (mm) whose wrapped layout fits box_w x box_h.

    Two phases: bisect on the block height (monotonic in cap height), then
    walk down in 1% steps until the ink width also fits - cursive swashes
    overshoot the wrap width by a hair, and where they land shifts with every
    re-wrap, so the width test is not monotonic and cannot be bisected.
    """
    def layout(h):
        _, info = text_to_polylines(
            text, fontname=fontname, height=h, line_spacing=line_spacing,
            char_spacing=char_spacing, align=align, max_width=box_w,
            origin=(0.0, 0.0), smooth=smooth, smooth_step=smooth_step,
            corner_angle=corner_angle, paragraph_gap=paragraph_gap)
        return info

    lo, hi = 0.2, float(box_h)
    for _ in range(30):
        mid = (lo + hi) / 2.0
        try:
            ok = layout(mid)["height"] <= box_h * 1.001
        except SystemExit:
            ok = False
        if ok:
            lo = mid
        else:
            hi = mid

    h = math.floor(lo * 100) / 100.0
    while h >= 0.2:
        try:
            info = layout(h)
            if info["width"] <= box_w * 1.001 and info["height"] <= box_h * 1.001:
                return h              # verified at this exact value
        except SystemExit:
            pass
        h = math.floor(h * 0.99 * 100) / 100.0
    return None


def merge_polylines(polys, tol=1e-6):
    """Join consecutive strokes that start exactly where the previous ended."""
    out = []
    for p in polys:
        if out and abs(out[-1][-1][0] - p[0][0]) < tol and abs(out[-1][-1][1] - p[0][1]) < tol:
            out[-1].extend(p[1:])
        else:
            out.append(list(p))
    return out

# ---------------------------------------------------------------- smoothing
#
# Hershey fonts store curves as short straight segments (1960s plotter data),
# which looks "shaky" at pen-plotter sizes. We fit a centripetal Catmull-Rom
# spline through the points of each stroke and resample it finely, so curves
# become actual curves. Genuine sharp corners (above `corner_deg` of turn)
# are preserved by splitting the spline there.


def _dedupe(pts, tol=1e-6):
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) > tol or abs(p[1] - out[-1][1]) > tol:
            out.append(p)
    return out


def _split_at_corners(pts, corner_deg):
    runs, cur = [], [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        n1 = math.hypot(*v1)
        n2 = math.hypot(*v2)
        cur.append(b)
        if n1 < 1e-9 or n2 < 1e-9:
            continue
        cos_t = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
        if math.degrees(math.acos(cos_t)) > corner_deg:
            runs.append(cur)
            cur = [b]
    cur.append(pts[-1])
    runs.append(cur)
    return runs


def _catmull_rom(run, step):
    """Centripetal Catmull-Rom through all points of `run`, sampled every ~step mm."""
    if len(run) < 3:
        return list(run)

    def d(a, b):
        return math.hypot(b[0] - a[0], b[1] - a[1])

    # reflect the ends to get natural end tangents
    pts = [(2 * run[0][0] - run[1][0], 2 * run[0][1] - run[1][1])] + list(run) + \
          [(2 * run[-1][0] - run[-2][0], 2 * run[-1][1] - run[-2][1])]
    out = [run[0]]
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        t0 = 0.0
        t1 = t0 + max(d(p0, p1) ** 0.5, 1e-9)
        t2 = t1 + max(d(p1, p2) ** 0.5, 1e-9)
        t3 = t2 + max(d(p2, p3) ** 0.5, 1e-9)
        n = max(2, int(math.ceil(d(p1, p2) / step)))
        for j in range(1, n + 1):
            t = t1 + (t2 - t1) * j / n

            def lp(pa, pb, ta, tb):
                if tb - ta < 1e-12:
                    return pa
                w = (t - ta) / (tb - ta)
                return (pa[0] + (pb[0] - pa[0]) * w, pa[1] + (pb[1] - pa[1]) * w)

            a1 = lp(p0, p1, t0, t1)
            a2 = lp(p1, p2, t1, t2)
            a3 = lp(p2, p3, t2, t3)
            b1 = lp(a1, a2, t0, t2)
            b2 = lp(a2, a3, t1, t3)
            out.append(lp(b1, b2, t1, t2))
    return out


def smooth_polyline(pts, step=0.25, corner_deg=75.0):
    pts = _dedupe(pts)
    if len(pts) < 3:
        return pts
    out = []
    for run in _split_at_corners(pts, corner_deg):
        seg = _catmull_rom(run, step)
        out.extend(seg[1:] if out else seg)
    return out

# ---------------------------------------------------------------- g-code

def _fmt(v):
    s = "%.4f" % v
    s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def polylines_to_gcode(polys, travel_feed=3000, draw_feed=3000, power=255,
                       pen_delay=0.4, pen_down="M03", pen_up="M05 G4 P0.3 S0",
                       go_home=True):
    """Emit G-code in the Doesbot / Candle dialect (M03 pen down, M05 pen up)."""
    g = []
    g.append(pen_up)                       # make sure the pen starts lifted
    g.append("")
    g.append("G90")                        # absolute coordinates
    g.append("G21")                        # millimetres
    g.append("G1 F%s" % _fmt(travel_feed))
    for poly in polys:
        x0, y0 = poly[0]
        g.append("G1 X%s Y%s" % (_fmt(x0), _fmt(y0)))     # travel, pen up
        g.append("G4 P0")
        g.append("%s S%s" % (pen_down, _fmt(power)))       # pen down
        g.append("G4 P%s" % _fmt(pen_delay))               # wait for pen to touch
        g.append("G1 F%s" % _fmt(draw_feed))
        for (x, y) in poly[1:]:
            g.append("G1 X%s Y%s" % (_fmt(x), _fmt(y)))
        g.append("G4 P0")
        g.append(pen_up)                                   # pen up
        g.append("G1 F%s" % _fmt(travel_feed))
    if go_home:
        g.append("G1 X0 Y0")
    g.append("")
    return "\n".join(g)


def plot_stats(polys, travel_feed, draw_feed, pen_delay):
    def dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])
    draw = travel = 0.0
    prev = (0.0, 0.0)
    for poly in polys:
        travel += dist(prev, poly[0])
        for a, b in zip(poly, poly[1:]):
            draw += dist(a, b)
        prev = poly[-1]
    travel += dist(prev, (0.0, 0.0))
    minutes = draw / draw_feed + travel / travel_feed \
        + len(polys) * (pen_delay + 0.3) / 60.0
    return draw, travel, minutes

# ---------------------------------------------------------------- svg preview

def polylines_to_svg(polys, stroke_mm=0.5):
    xs = [p[0] for poly in polys for p in poly] + [0.0]
    ys = [p[1] for poly in polys for p in poly] + [0.0]
    pad = 6.0
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    w, h = max_x - min_x, max_y - min_y

    def sx(x):
        return x - min_x

    def sy(y):
        return max_y - y          # flip: machine Y-up -> SVG y-down

    parts = []
    parts.append('<svg xmlns="http://www.w3.org/2000/svg" width="%.1fmm" height="%.1fmm" '
                 'viewBox="0 0 %.2f %.2f">' % (w, h, w, h))
    parts.append('<rect width="%.2f" height="%.2f" fill="white"/>' % (w, h))
    # machine origin crosshair
    ox, oy = sx(0.0), sy(0.0)
    parts.append('<g stroke="#d33" stroke-width="0.3">'
                 '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>'
                 '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/></g>'
                 % (ox - 3, oy, ox + 3, oy, ox, oy - 3, ox, oy + 3))
    parts.append('<text x="%.2f" y="%.2f" font-size="3" fill="#d33" '
                 'font-family="sans-serif">machine 0,0</text>' % (ox + 1.5, oy + 4.5))
    # the strokes
    for poly in polys:
        pts = " ".join("%.3f,%.3f" % (sx(x), sy(y)) for (x, y) in poly)
        parts.append('<polyline points="%s" fill="none" stroke="#111" '
                     'stroke-width="%.2f" stroke-linecap="round" '
                     'stroke-linejoin="round"/>' % (pts, stroke_mm))
    parts.append("</svg>")
    return "\n".join(parts)

# ---------------------------------------------------------------- cli

def build_parser():
    p = argparse.ArgumentParser(
        description="Turn text into single-stroke handwriting G-code for the AX5 plotter.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Examples:\n'
               '  python text2gcode.py "Hello world" -o hello.gcode\n'
               '  python text2gcode.py "Line one\\nLine two" --align center --height 12\n'
               '  python text2gcode.py --file letter.txt --max-width 180\n')
    p.add_argument("text", nargs="?", help='Text to plot. Use \\n for a new line.')
    p.add_argument("--file", help="Read the text from a UTF-8 text file instead.")
    p.add_argument("-o", "--out", default="out/handwriting.gcode", help="Output .gcode path (default: out/handwriting.gcode)")
    p.add_argument("--font", default="scripts", help="Hershey font name (default: scripts). See --list-fonts.")
    p.add_argument("--list-fonts", action="store_true", help="List available fonts and exit.")
    p.add_argument("--height", type=float, default=10.0, help="Capital letter height in mm (default: 10)")
    p.add_argument("--line-spacing", type=float, default=1.0, help="Line pitch as a multiple of the font's natural ascender-to-descender span (default: 1.0 = lines just clear; 0.85 tighter, 1.2 airier)")
    p.add_argument("--char-spacing", type=float, default=0.0, help="Extra space between letters in mm; negative squeezes cursive together (default: 0)")
    p.add_argument("--align", choices=["left", "center", "right"], default="left")
    p.add_argument("--max-width", type=float, help="Wrap lines longer than this width in mm.")
    p.add_argument("--fit", help='Auto-size the text to fill a box, e.g. "65x80" (width x height in mm). Overrides --height and --max-width.')
    p.add_argument("--paragraph-gap", type=float, default=1.0, help="Height of blank lines as a fraction of a normal line (default: 1.0; try 0.5 on small cards)")
    p.add_argument("--origin", default="10,10", help='Bottom-left corner of the text block in mm, "X,Y" from machine zero (default: 10,10)')
    p.add_argument("--travel-feed", type=float, default=3000, help="Pen-up move speed mm/min (default: 3000)")
    p.add_argument("--draw-feed", type=float, default=3000, help="Drawing speed mm/min (default: 3000)")
    p.add_argument("--power", type=int, default=255, help="S value sent with pen-down M03 (default: 255)")
    p.add_argument("--pen-delay", type=float, default=0.4, help="Dwell after pen down, seconds (default: 0.4)")
    p.add_argument("--pen-down-cmd", default="M03", help='Pen down command (default: "M03")')
    p.add_argument("--pen-up-cmd", default="M05 G4 P0.3 S0", help='Pen up command (default: "M05 G4 P0.3 S0")')
    p.add_argument("--no-home", action="store_true", help="Do not return to X0 Y0 at the end.")
    p.add_argument("--no-svg", action="store_true", help="Skip writing the .preview.svg file.")
    p.add_argument("--no-smooth", action="store_true", help="Keep the raw segmented Hershey strokes (old behaviour).")
    p.add_argument("--smooth-step", type=float, default=0.25, help="Spline sampling distance in mm; larger = smaller files (default: 0.25)")
    p.add_argument("--corner-angle", type=float, default=75.0, help="Turns sharper than this many degrees stay sharp corners (default: 75)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.list_fonts:
        print("Hershey fonts (built in, use with --font):\n")
        for name in available_fonts():
            note = FONT_NOTES.get(name, "")
            print("  %-12s %s" % (name, note))
        svgs = list_svg_fonts()
        if svgs:
            print("\nSingle-line SVG fonts in fonts\\ (smooth curves, use with --font):\n")
            for f in svgs:
                stem = os.path.splitext(f)[0]
                try:
                    fam = SvgFont(os.path.join(svg_font_dir(), f)).name
                except Exception as e:
                    fam = "unreadable: %s" % e
                print("  %-22s %s" % (stem.lower(), fam))
        return 0

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read().rstrip("\n")
    elif args.text is not None:
        text = args.text.replace("\\n", "\n")
    else:
        build_parser().print_help()
        return 1

    try:
        ox, oy = (float(v) for v in args.origin.split(","))
    except ValueError:
        raise SystemExit('--origin must look like "10,10"')

    if args.fit:
        try:
            box_w, box_h = (float(v) for v in re.split(r"[x,X]", args.fit))
        except ValueError:
            raise SystemExit('--fit must look like "65x80" (width x height in mm)')
        h = fit_text(text, args.font, box_w, box_h,
                     line_spacing=args.line_spacing, char_spacing=args.char_spacing,
                     align=args.align, paragraph_gap=args.paragraph_gap,
                     smooth=not args.no_smooth, smooth_step=args.smooth_step,
                     corner_angle=args.corner_angle)
        if h is None:
            raise SystemExit("Cannot fit this text into %.0f x %.0f mm - "
                             "shorten the text or enlarge the box." % (box_w, box_h))
        args.height = math.floor(h * 100) / 100.0
        args.max_width = box_w
        print("Auto-fit: cap height %.2f mm fills the %.0f x %.0f mm box"
              % (args.height, box_w, box_h))

    polys, info = text_to_polylines(
        text, fontname=args.font, height=args.height,
        line_spacing=args.line_spacing, char_spacing=args.char_spacing,
        align=args.align, max_width=args.max_width, origin=(ox, oy),
        smooth=not args.no_smooth, smooth_step=args.smooth_step,
        corner_angle=args.corner_angle, paragraph_gap=args.paragraph_gap)

    gcode = polylines_to_gcode(
        polys, travel_feed=args.travel_feed, draw_feed=args.draw_feed,
        power=args.power, pen_delay=args.pen_delay,
        pen_down=args.pen_down_cmd, pen_up=args.pen_up_cmd,
        go_home=not args.no_home)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.out, "w", newline="\r\n", encoding="ascii") as f:
        f.write(gcode)

    svg_path = None
    if not args.no_svg:
        svg_path = os.path.splitext(args.out)[0] + ".preview.svg"
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(polylines_to_svg(polys))

    x0, y0, x1, y1 = info["bbox"]
    draw, travel, minutes = plot_stats(polys, args.travel_feed, args.draw_feed, args.pen_delay)
    print("Wrote %s" % args.out)
    if svg_path:
        print("Wrote %s  (open in a browser to check before plotting)" % svg_path)
    print("Font: %s   lines: %d   pen strokes: %d" % (info["font"], info["lines"], len(polys)))
    print("Text block: %.1f x %.1f mm   on paper: X %.1f..%.1f  Y %.1f..%.1f mm"
          % (info["width"], info["height"], x0, x1, y0, y1))
    print("Ink %.0f mm, travel %.0f mm, roughly %.1f min at F%.0f"
          % (draw, travel, minutes, args.draw_feed))
    if info["dropped"]:
        print("Warning: no glyph for: %s  (replaced with spaces)"
              % " ".join(sorted(info["dropped"])))
    print("Reminder: zero the machine (pen at bottom-left of the paper) before sending.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
