#!/usr/bin/env python3
"""The address block: optional, right half of the card, same G-code file.

Run from the postcard-plotter folder:   python tests/test_address.py

Needs only lib/ (no ../text2gcode), so it runs on a fresh clone.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
sys.path[:0] = [WEB, os.path.join(WEB, "lib")]

import webapi

TEXT = ("Dear friend,\n\nThank you for your faithful partnership in the Gospel "
        "with us.\n\nYours,\n\nThe team")
ADDRESS = "Mr & Mrs J Smith\n14 Church Lane\nLittle Bampton\nSt Albans\nHertfordshire\nAL3 4QP"


def call(fn, **p):
    r = json.loads(fn(json.dumps(p)))
    assert r["ok"], r.get("error")
    return r


def xy_of(gcode):
    """All X/Y pairs moved to, in order."""
    pts = []
    for line in gcode.splitlines():
        if line.startswith("G1 X"):
            x, y = line[4:].split(" Y")
            pts.append((float(x), float(y)))
    return pts


def main():
    d = webapi._params("{}")

    # 1. No address -> exactly the output we had before the address existed.
    base = call(webapi.generate, text=TEXT)
    same = call(webapi.generate, text=TEXT, address="   \n \n")
    assert base["gcode"] == same["gcode"], "blank address changed the G-code"
    assert base["address"] is None

    # 2. With an address: message G-code is an unchanged prefix, the address
    #    follows, and every address point lies inside the address area
    #    (machine zero at the writing-area corner, so shift by box_x/box_y).
    both = call(webapi.generate, text=TEXT, address=ADDRESS)
    body = base["gcode"].split("\r\nG1 X0 Y0")[0]          # drop the go-home
    assert both["gcode"].startswith(body), "message part changed when an address was added"
    n_msg = len(xy_of(base["gcode"])) - 1                   # minus the go-home
    addr_pts = xy_of(both["gcode"])[n_msg:-1]
    assert addr_pts, "no address moves emitted"
    ax0, ay0 = d["addr_x"] - d["box_x"], d["addr_y"] - d["box_y"]
    for (x, y) in addr_pts:
        assert ax0 - 0.05 <= x <= ax0 + d["addr_w"] + 0.05, ("x outside address area", x)
        assert ay0 - 0.05 <= y <= ay0 + d["addr_h"] + 0.05, ("y outside address area", y)
    assert both["address"]["lines"] == 6
    assert both["info"]["strokes"] > base["info"]["strokes"]

    # 3. Fit reserves room for addr_lines: a 3-line address is not bigger
    #    than the 6-line reservation allows, and the full UK address fits.
    short = call(webapi.preview, text=TEXT, address="Jo Bloggs\nLondon\nSW1A 1AA")
    full = call(webapi.preview, text=TEXT, address=ADDRESS)
    assert short["address"]["info"]["height"] <= d["addr_h"] / 2 + 0.5, short["address"]["info"]
    assert full["address"]["info"]["width"] <= d["addr_w"] + 0.05
    assert full["address"]["info"]["height"] <= d["addr_h"] + 0.05
    assert not full["warnings"], full["warnings"]

    # 4. Lines are never re-wrapped: a long line shrinks the whole block.
    wide = call(webapi.preview, text=TEXT,
                address="Flat 3, 42 Buckingham Palace Road\nLondon\nSW1W 0RE")
    assert wide["address"]["info"]["lines"] == 3
    assert wide["address"]["info"]["cap_height"] < short["address"]["info"]["cap_height"]

    # 5. Fixed mode honours the height and warns on overflow instead of hiding it.
    fixed = call(webapi.preview, text=TEXT, address=ADDRESS, addr_mode="fixed", addr_height=6)
    assert fixed["address"]["info"]["cap_height"] == 6.0
    assert any("overflows the address area" in w for w in fixed["warnings"]), fixed["warnings"]

    # 6. Address only (pre-addressing a batch of cards) works too.
    only = call(webapi.generate, text="", address=ADDRESS)
    assert only["message"] is None and only["address"]["lines"] == 6

    # 7. Card-corner zero: the address lands at addr_x/addr_y on the card.
    card = call(webapi.generate, text="", address=ADDRESS, zero_at="card")
    xs = [x for (x, _) in xy_of(card["gcode"])[:-1]]
    assert abs(min(xs) - d["addr_x"]) < 0.05, min(xs)

    print("OK - address block: optional, placed in its area, never re-wrapped, "
          "message G-code untouched")


if __name__ == "__main__":
    main()
