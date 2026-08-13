#!/usr/bin/env python3
"""Guard: the web app must emit exactly the same G-code as the command line.

Run from the text2gcode-web folder:   python tests/test_fidelity.py
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
LIB = os.path.normpath(os.path.join(WEB, "..", "text2gcode"))
sys.path[:0] = [WEB, LIB]

import webapi

GOLDEN = os.path.normpath(os.path.join(LIB, "out", "postcard_65x80.gcode"))

# Exactly the CLI invocation that produced the golden file:
#   --file postcard.txt --font emsallure --fit 65x80 --paragraph-gap 0.5
#   --draw-feed 1500 --origin 0,0
PARAMS = {
    "text": open(os.path.join(LIB, "postcard.txt"), encoding="utf-8").read().rstrip(),
    "font": "emsallure", "mode": "fit", "box_w": 65, "box_h": 80,
    "align": "left", "valign": "bottom", "line_spacing": 1.0,
    "paragraph_gap": 0.5, "draw_feed": 1500, "zero_at": "box",
}


def main():
    if not os.path.exists(GOLDEN):
        sys.exit("Missing golden file: %s" % GOLDEN)
    web = json.loads(webapi.generate(json.dumps(PARAMS)))
    if not web["ok"]:
        sys.exit("generate() failed: %s" % web.get("error"))
    golden = open(GOLDEN, newline="").read()
    if web["gcode"] != golden:
        a, b = web["gcode"].splitlines(), golden.splitlines()
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                sys.exit("MISMATCH at line %d:\n  web %r\n  cli %r" % (i, x, y))
        sys.exit("MISMATCH: %d web lines vs %d cli lines" % (len(a), len(b)))
    print("OK - web G-code is byte-identical to the CLI (%d bytes)" % len(golden))


if __name__ == "__main__":
    main()
