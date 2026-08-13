#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""webapi.py - thin JSON adapter between the browser UI and text2gcode.py.

Every function takes and returns JSON strings, so the JavaScript side never
has to touch Python objects. All geometry still comes from text2gcode.py
unchanged, so the web app and the command line produce identical G-code.

Coordinate model
----------------
Text is laid out with its bottom-left at (0, 0), then placed:

  * inside the writing area, using `align` horizontally and `valign`
    vertically;
  * the writing area sits at (box_x, box_y) on the card, measured from the
    card's bottom-left corner, Y up.

`preview()` returns the ink already flipped into SVG space (Y down, relative
to the card's top-left) so the page can drop the path straight into an <svg>.
`generate()` emits machine coordinates, offset so that whichever corner the
user picked as machine zero really is 0,0.
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import text2gcode as t2g  # noqa: E402

# Uploaded fonts live here for the lifetime of the browser tab and nowhere
# else - never written to disk, gone when the tab closes or on forget_font().
_UPLOADED = {}

_FONT_NOTES = {
    "emsallure": "flowing formal cursive",
    "emsfelix": "casual italic handwriting",
    "emselfin": "playful upright handwriting",
    "emsreadability": "clean print handwriting",
    "emsreadabilityitalic": "clean print, italic",
    "emsnixish": "typewriter-like",
    "emsnixishitalic": "typewriter-like, italic",
    "emsosmotron": "rounded techno",
    "emstech": "angular tech print",
}

_HERSHEY_SHOW = [
    ("scripts", "cursive script"),
    ("cursive", "cursive, lighter"),
    ("futural", "single-stroke print"),
    ("timesi", "serif italic"),
    ("timesr", "serif roman"),
    ("gothiceng", "blackletter"),
    ("greek", "Greek alphabet"),
    ("cyrillic", "Cyrillic alphabet"),
]

_DEFAULTS = {
    "text": "",
    "font": "emsallure",
    "mode": "fit",              # "fit" | "fixed"
    "box_w": 65.0, "box_h": 80.0,
    "box_x": 6.0, "box_y": 12.5,
    "card_w": 150.0, "card_h": 105.0,
    "height": 4.0,
    "max_width": None,
    "align": "left",            # left | center | right
    "valign": "top",            # top | middle | bottom
    "line_spacing": 1.0,
    "paragraph_gap": 0.5,
    "char_spacing": 0.0,
    "smooth": True,
    "smooth_step": 0.25,
    "corner_angle": 75.0,
    "zero_at": "box",           # "box" (writing-area corner) | "card"
    "draw_feed": 1500.0,
    "travel_feed": 3000.0,
    "power": 255,
    "pen_delay": 0.4,
    "pen_down_cmd": "M03",
    "pen_up_cmd": "M05 G4 P0.3 S0",
    "go_home": True,
}


def _params(raw):
    p = dict(_DEFAULTS)
    p.update(json.loads(raw) if isinstance(raw, str) else (raw or {}))
    return p


def _font_for(p):
    f = p.get("font")
    return _UPLOADED[f] if f in _UPLOADED else f


def list_fonts():
    """Fonts the UI can offer, grouped for the dropdown."""
    out = []
    for f in t2g.list_svg_fonts():
        stem = os.path.splitext(f)[0]
        fid = stem.lower()
        try:
            label = t2g.SvgFont(os.path.join(t2g.svg_font_dir(), f)).name
        except Exception:
            continue
        out.append({"id": fid, "label": label, "group": "Smooth (EMS)",
                    "note": _FONT_NOTES.get(fid, ""), "kind": "svg"})
    for name, note in _HERSHEY_SHOW:
        if hasattr(t2g.hersheydata, name):
            out.append({"id": name, "label": name, "group": "Classic (Hershey)",
                        "note": note, "kind": "hershey"})
    for fid, font in _UPLOADED.items():
        out.append({"id": fid, "label": font.name + " (uploaded)",
                    "group": "Uploaded", "note": "", "kind": "svg"})
    return json.dumps(out)


def _layout(p):
    """Lay the text out at (0,0) and return (polylines, info, height_used)."""
    font = _font_for(p)
    height = float(p["height"])
    wrap = p.get("max_width")

    if p["mode"] == "fit":
        found = t2g.fit_text(
            p["text"], font, float(p["box_w"]), float(p["box_h"]),
            line_spacing=float(p["line_spacing"]),
            char_spacing=float(p["char_spacing"]),
            align=p["align"], paragraph_gap=float(p["paragraph_gap"]),
            smooth=bool(p["smooth"]), smooth_step=float(p["smooth_step"]),
            corner_angle=float(p["corner_angle"]))
        if found is None:
            raise ValueError(
                "This text will not fit in %g x %g mm, even at the smallest "
                "size. Shorten it or enlarge the writing area."
                % (float(p["box_w"]), float(p["box_h"])))
        height = found
        wrap = float(p["box_w"])

    polys, info = t2g.text_to_polylines(
        p["text"], fontname=font, height=height,
        line_spacing=float(p["line_spacing"]),
        char_spacing=float(p["char_spacing"]),
        align=p["align"], max_width=wrap, origin=(0.0, 0.0),
        smooth=bool(p["smooth"]), smooth_step=float(p["smooth_step"]),
        corner_angle=float(p["corner_angle"]),
        paragraph_gap=float(p["paragraph_gap"]))
    return polys, info, height


def _place(polys, info, p):
    """Offset the block inside the writing area per align / valign."""
    box_w, box_h = float(p["box_w"]), float(p["box_h"])
    w, h = info["width"], info["height"]
    if p["align"] == "center":
        dx = (box_w - w) / 2.0
    elif p["align"] == "right":
        dx = box_w - w
    else:
        dx = 0.0
    if p["valign"] == "middle":
        dy = (box_h - h) / 2.0
    elif p["valign"] == "bottom":
        dy = 0.0
    else:                                  # top - letters start at the top
        dy = box_h - h
    return [[(x + dx, y + dy) for (x, y) in poly] for poly in polys], dx, dy


def _path_d(polys, flip_h=None):
    """Compact SVG path. With flip_h, convert Y-up mm into SVG Y-down space."""
    parts = []
    for poly in polys:
        pts = [(x, flip_h - y if flip_h is not None else y) for (x, y) in poly]
        parts.append("M" + " L".join("%.3f %.3f" % q for q in pts))
    return " ".join(parts)


def _stats(polys, p, info, height):
    draw, travel, minutes = t2g.plot_stats(
        polys, float(p["travel_feed"]), float(p["draw_feed"]),
        float(p["pen_delay"]))
    return {
        "width": round(info["width"], 2),
        "height": round(info["height"], 2),
        "lines": info["lines"],
        "strokes": len(polys),
        "cap_height": round(height, 2),
        "ink_mm": round(draw),
        "travel_mm": round(travel),
        "minutes": round(minutes, 1),
        "dropped": sorted(info["dropped"]),
    }


def _warnings(info, p, stats):
    w = []
    if info["dropped"]:
        w.append("No glyph for: %s (drawn as spaces)."
                 % " ".join(sorted(info["dropped"])))
    over_w = stats["width"] - float(p["box_w"])
    over_h = stats["height"] - float(p["box_h"])
    if over_w > 0.05 or over_h > 0.05:
        bits = []
        if over_w > 0.05:
            bits.append("%.1f mm too wide" % over_w)
        if over_h > 0.05:
            bits.append("%.1f mm too tall" % over_h)
        w.append("Text overflows the writing area: " + " and ".join(bits) + ".")
    if stats["cap_height"] < 2.0:
        w.append("Letters are very small (%.1f mm capitals) - use a 0.2 mm "
                 "pen and test on scrap paper first." % stats["cap_height"])
    return w


def preview(raw):
    """Ink path in SVG space plus stats, for live rendering on the card."""
    p = _params(raw)
    if not p["text"].strip():
        return json.dumps({"ok": True, "empty": True})
    try:
        polys, info, height = _layout(p)
    except (ValueError, SystemExit) as e:
        return json.dumps({"ok": False, "error": str(e)})

    placed, _, _ = _place(polys, info, p)
    card = [[(x + float(p["box_x"]), y + float(p["box_y"])) for (x, y) in poly]
            for poly in placed]
    stats = _stats(polys, p, info, height)
    return json.dumps({
        "ok": True, "empty": False,
        "ink_path_d": _path_d(card, flip_h=float(p["card_h"])),
        "info": stats,
        "warnings": _warnings(info, p, stats),
    })


def generate(raw):
    """Final G-code in machine coordinates."""
    p = _params(raw)
    if not p["text"].strip():
        return json.dumps({"ok": False, "error": "Nothing to plot - the text is empty."})
    try:
        polys, info, height = _layout(p)
    except (ValueError, SystemExit) as e:
        return json.dumps({"ok": False, "error": str(e)})

    placed, _, _ = _place(polys, info, p)
    if p["zero_at"] == "card":
        # machine zero is the card corner, so keep the writing-area offset
        placed = [[(x + float(p["box_x"]), y + float(p["box_y"]))
                   for (x, y) in poly] for poly in placed]

    gcode = t2g.polylines_to_gcode(
        placed, travel_feed=float(p["travel_feed"]),
        draw_feed=float(p["draw_feed"]), power=int(p["power"]),
        pen_delay=float(p["pen_delay"]), pen_down=p["pen_down_cmd"],
        pen_up=p["pen_up_cmd"], go_home=bool(p["go_home"]))

    stats = _stats(placed, p, info, height)
    minx = min(x for poly in placed for (x, _) in poly)
    miny = min(y for poly in placed for (_, y) in poly)
    return json.dumps({
        "ok": True,
        "gcode": gcode.replace("\n", "\r\n"),
        "info": stats,
        "warnings": _warnings(info, p, stats),
        "starts_at": [round(minx, 2), round(miny, 2)],
    })


def add_font(name, svg_text):
    """Register an uploaded SVG font, in memory only."""
    try:
        font = t2g.SvgFont.from_string(svg_text, os.path.splitext(name)[0])
    except Exception as e:
        return json.dumps({"ok": False,
                           "error": "Could not read this as an SVG font: %s" % e})

    letters = [c for c in "abcdefghijklmnopqrstuvwxyz" if font.has(c)]
    if len(letters) < 10:
        return json.dumps({"ok": False,
                           "error": "This font has almost no letters in it "
                                    "(%d of 26)." % len(letters)})

    fid = "up_" + "".join(ch for ch in name.lower() if ch.isalnum())[:24]
    _UPLOADED[fid] = font
    return json.dumps({"ok": True, "id": fid, "label": font.name + " (uploaded)",
                       "warnings": _outline_check(font, letters)})


def _outline_check(font, letters):
    """Warn when an uploaded font is an outline font, whose letters would plot
    as hollow double contours - the exact trap this whole tool exists to avoid."""
    closed = 0
    for ch in letters[:16]:
        for s in font.strokes(ch, 1.0):
            if len(s) > 3:
                x0, y0 = s[0]
                x1, y1 = s[-1]
                if abs(x0 - x1) < 1.0 and abs(y0 - y1) < 1.0:
                    closed += 1
                    break
    if closed >= max(4, len(letters[:16]) * 0.6):
        return ["This looks like an OUTLINE font: most letters are closed "
                "loops, so they will plot as hollow double contours rather "
                "than single pen strokes. Single-line fonts (EMS, Hershey) "
                "draw each stroke once."]
    return []


def forget_font(fid):
    _UPLOADED.pop(fid, None)
    return json.dumps({"ok": True})


def defaults():
    return json.dumps(_DEFAULTS)
