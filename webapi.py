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

The optional address is a second block laid out the same way inside its own
area (addr_x, addr_y, addr_w, addr_h) on the right half of the card. Its lines
are never re-wrapped - an address is plotted exactly line for line as typed -
so "fit" shrinks the letters until the longest line fits the width and until
`addr_lines` lines (a typical UK address needs 5-6) fit the height.

`preview()` returns the ink already flipped into SVG space (Y down, relative
to the card's top-left) so the page can drop the path straight into an <svg>.
`generate()` emits machine coordinates, offset so that whichever corner the
user picked as machine zero really is 0,0. Message and address go into the
same G-code file, message first.
"""

import json
import math
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
    # the address block, on the right half of the card
    "address": "",
    "addr_mode": "fit",         # "fit" | "fixed"
    "addr_x": 80.0, "addr_y": 12.5,     # 5 mm right of the centre divider
    "addr_w": 62.0, "addr_h": 60.0,     # ends below the stamp box
    "addr_height": 4.0,         # cap height in fixed mode
    "addr_lines": 6,            # fit mode leaves room for at least this many
    "addr_valign": "top",
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
    """Lay the message out at (0,0) and return (polylines, info, height_used)."""
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


def _address_lines(p):
    """The address as typed, minus leading/trailing blank lines."""
    lines = [ln.rstrip() for ln in str(p.get("address") or "").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _layout_address(p):
    """Lay the address out at (0,0), one line per typed line, never wrapped.

    Returns (polylines, info, height_used). In fit mode the cap height is
    the largest that satisfies all three of:
      * the longest line fits addr_w,
      * the typed lines fit addr_h,
      * `addr_lines` lines would fit addr_h - so a 3-line address is not
        blown up to fill the box, and every card in a batch comes out at
        the same size whether its address has 3 lines or 6.
    Nothing is re-wrapped, so width and height are both linear in the cap
    height and one trial layout is enough to solve for it.
    """
    font = _font_for(p)
    text = "\n".join(_address_lines(p))
    ls = float(p["line_spacing"])

    def layout(h):
        return t2g.text_to_polylines(
            text, fontname=font, height=h, line_spacing=ls,
            char_spacing=float(p["char_spacing"]), align="left",
            max_width=None, origin=(0.0, 0.0), smooth=bool(p["smooth"]),
            smooth_step=float(p["smooth_step"]),
            corner_angle=float(p["corner_angle"]), paragraph_gap=0.5)

    height = float(p["addr_height"])
    if p["addr_mode"] == "fit":
        box_w, box_h = float(p["addr_w"]), float(p["addr_h"])
        trial = 10.0
        _, info = layout(trial)
        f = t2g.resolve_font(font)
        n = max(int(p["addr_lines"]), 1)
        by_width = trial * box_w / info["width"] if info["width"] else box_h
        by_height = trial * box_h / info["height"] if info["height"] else box_h
        by_lines = f.cap * box_h / (n * f.line_height * ls)
        height = min(by_width, by_height, by_lines)
        if height < 0.2:
            raise ValueError(
                "The address will not fit in %g x %g mm. Shorten the longest "
                "line or enlarge the address area." % (box_w, box_h))
        # the linear solve ignores char_spacing (a constant per glyph), so
        # verify and nudge down until it really fits
        height = math.floor(height * 100) / 100.0
        while height >= 0.2:
            _, info = layout(height)
            if info["width"] <= box_w * 1.001 and info["height"] <= box_h * 1.001:
                break
            height = math.floor(height * 0.99 * 100) / 100.0

    polys, info = layout(height)
    return polys, info, height


def _place(polys, info, box_w, box_h, align, valign):
    """Offset a block inside its box per align / valign."""
    w, h = info["width"], info["height"]
    if align == "center":
        dx = (box_w - w) / 2.0
    elif align == "right":
        dx = box_w - w
    else:
        dx = 0.0
    if valign == "middle":
        dy = (box_h - h) / 2.0
    elif valign == "bottom":
        dy = 0.0
    else:                                  # top - letters start at the top
        dy = box_h - h
    return [[(x + dx, y + dy) for (x, y) in poly] for poly in polys]


def _shift(polys, dx, dy):
    return [[(x + dx, y + dy) for (x, y) in poly] for poly in polys]


def _path_d(polys, flip_h=None):
    """Compact SVG path. With flip_h, convert Y-up mm into SVG Y-down space."""
    parts = []
    for poly in polys:
        pts = [(x, flip_h - y if flip_h is not None else y) for (x, y) in poly]
        parts.append("M" + " L".join("%.3f %.3f" % q for q in pts))
    return " ".join(parts)


def _block_info(info, height):
    return {
        "width": round(info["width"], 2),
        "height": round(info["height"], 2),
        "lines": info["lines"],
        "cap_height": round(height, 2),
        "dropped": sorted(info["dropped"]),
    }


def _plot_info(all_polys, p):
    draw, travel, minutes = t2g.plot_stats(
        all_polys, float(p["travel_feed"]), float(p["draw_feed"]),
        float(p["pen_delay"]))
    return {
        "strokes": len(all_polys),
        "ink_mm": round(draw),
        "travel_mm": round(travel),
        "minutes": round(minutes, 1),
    }


def _block_warnings(info, box_w, box_h, what, area):
    w = []
    if info["dropped"]:
        w.append("No glyph for: %s (drawn as spaces)."
                 % " ".join(info["dropped"]))
    over_w = info["width"] - box_w
    over_h = info["height"] - box_h
    if over_w > 0.05 or over_h > 0.05:
        bits = []
        if over_w > 0.05:
            bits.append("%.1f mm too wide" % over_w)
        if over_h > 0.05:
            bits.append("%.1f mm too tall" % over_h)
        w.append("%s overflows the %s area: %s." % (what, area, " and ".join(bits)))
    if info["cap_height"] < 2.0:
        w.append("%s letters are very small (%.1f mm capitals) - use a 0.2 mm "
                 "pen and test on scrap paper first."
                 % (what, info["cap_height"]))
    return w


def _compose(p):
    """Lay out both blocks, each placed inside its own area but still in that
    area's local coordinates (mm, Y up, from the area's bottom-left), with
    the area's position on the card as `origin`. Callers add the offset they
    need; keeping it out of here means the message, with machine zero at its
    own corner, is never shifted and never picks up float noise - the web
    G-code stays byte-identical to the CLI's."""
    out = {"message": None, "address": None}

    if p["text"].strip():
        polys, info, height = _layout(p)
        placed = _place(polys, info, float(p["box_w"]), float(p["box_h"]),
                        p["align"], p["valign"])
        binfo = _block_info(info, height)
        out["message"] = {
            "polys": placed, "info": binfo,
            "origin": (float(p["box_x"]), float(p["box_y"])),
            "warnings": _block_warnings(binfo, float(p["box_w"]),
                                        float(p["box_h"]), "Text", "writing"),
        }

    if _address_lines(p):
        polys, info, height = _layout_address(p)
        placed = _place(polys, info, float(p["addr_w"]), float(p["addr_h"]),
                        "left", p["addr_valign"])
        binfo = _block_info(info, height)
        out["address"] = {
            "polys": placed, "info": binfo,
            "origin": (float(p["addr_x"]), float(p["addr_y"])),
            "warnings": _block_warnings(binfo, float(p["addr_w"]),
                                        float(p["addr_h"]), "Address", "address"),
        }

    return out


def _assemble(c, zero=(0.0, 0.0)):
    """All polylines, message first, in coordinates whose 0,0 is `zero`
    (card coordinates). A block whose origin equals `zero` is not touched."""
    polys = []
    for key in ("message", "address"):
        b = c[key]
        if b is None:
            continue
        dx, dy = b["origin"][0] - zero[0], b["origin"][1] - zero[1]
        polys.extend(b["polys"] if dx == 0 and dy == 0 else _shift(b["polys"], dx, dy))
    return polys


def preview(raw):
    """Ink paths in SVG space plus stats, for live rendering on the card."""
    p = _params(raw)
    if not p["text"].strip() and not _address_lines(p):
        return json.dumps({"ok": True, "empty": True})
    try:
        c = _compose(p)
    except (ValueError, SystemExit) as e:
        return json.dumps({"ok": False, "error": str(e)})

    card_h = float(p["card_h"])
    warnings = []
    res = {"ok": True, "empty": False, "info": _plot_info(_assemble(c), p)}
    for key in ("message", "address"):
        b = c[key]
        if b is None:
            res[key] = None
            continue
        on_card = _shift(b["polys"], b["origin"][0], b["origin"][1])
        res[key] = {"ink_path_d": _path_d(on_card, flip_h=card_h),
                    "info": b["info"]}
        warnings.extend(b["warnings"])
    res["warnings"] = warnings
    return json.dumps(res)


def generate(raw):
    """Final G-code in machine coordinates. Message first, then the address."""
    p = _params(raw)
    if not p["text"].strip() and not _address_lines(p):
        return json.dumps({"ok": False,
                           "error": "Nothing to plot - the message and address are both empty."})
    try:
        c = _compose(p)
    except (ValueError, SystemExit) as e:
        return json.dumps({"ok": False, "error": str(e)})

    # machine zero: the writing area's corner (default) or the card's corner
    zero = (float(p["box_x"]), float(p["box_y"])) if p["zero_at"] == "box" else (0.0, 0.0)
    polys = _assemble(c, zero)

    gcode = t2g.polylines_to_gcode(
        polys, travel_feed=float(p["travel_feed"]),
        draw_feed=float(p["draw_feed"]), power=int(p["power"]),
        pen_delay=float(p["pen_delay"]), pen_down=p["pen_down_cmd"],
        pen_up=p["pen_up_cmd"], go_home=bool(p["go_home"]))

    warnings = []
    for key in ("message", "address"):
        if c[key] is not None:
            warnings.extend(c[key]["warnings"])
    minx = min(x for poly in polys for (x, _) in poly)
    miny = min(y for poly in polys for (_, y) in poly)
    return json.dumps({
        "ok": True,
        "gcode": gcode.replace("\n", "\r\n"),
        "info": _plot_info(polys, p),
        "message": c["message"] and c["message"]["info"],
        "address": c["address"] and c["address"]["info"],
        "warnings": warnings,
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
