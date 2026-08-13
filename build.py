#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build.py - package the plotter library + fonts into bundle.zip for the web app.

    python build.py

Two steps:

1. If ../text2gcode is present it is mirrored into lib/. That folder is the
   single source of truth; lib/ is a generated copy, never edited by hand.
2. lib/ + webapi.py are zipped into bundle.zip, which the page fetches at
   startup and unpacks inside Pyodide.

bundle.zip and lib/ are both committed, so a fresh clone can serve and rebuild
the site without needing ../text2gcode. GitHub Pages has no build step, which
is why the artifact lives in the repo rather than being produced on deploy.
"""

import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "text2gcode"))
LIB = os.path.join(HERE, "lib")
OUT = os.path.join(HERE, "bundle.zip")

MODULES = ["text2gcode.py", "hersheydata.py"]


def sync_lib():
    """Refresh lib/ from the upstream folder, if we can see it."""
    if not os.path.isdir(SRC):
        print("note: %s not found - building from the existing lib/ copy" % SRC)
        return False
    os.makedirs(os.path.join(LIB, "fonts"), exist_ok=True)
    for m in MODULES:
        shutil.copy2(os.path.join(SRC, m), os.path.join(LIB, m))
    for f in os.listdir(os.path.join(SRC, "fonts")):
        if f.lower().endswith(".svg") or f == "OFL.txt":
            shutil.copy2(os.path.join(SRC, "fonts", f),
                         os.path.join(LIB, "fonts", f))
    print("synced lib/ from %s" % SRC)
    return True


def main():
    sync_lib()

    missing = [m for m in MODULES if not os.path.exists(os.path.join(LIB, m))]
    if missing or not os.path.isdir(os.path.join(LIB, "fonts")):
        sys.exit("lib/ is incomplete (missing %s). Run this next to the "
                 "text2gcode folder at least once." % ", ".join(missing or ["fonts/"]))

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for m in MODULES:
            z.write(os.path.join(LIB, m), m)
        z.write(os.path.join(HERE, "webapi.py"), "webapi.py")
        n = 0
        for f in sorted(os.listdir(os.path.join(LIB, "fonts"))):
            if f.lower().endswith(".svg") or f == "OFL.txt":
                z.write(os.path.join(LIB, "fonts", f), "fonts/" + f)
                n += 1

    print("Wrote bundle.zip (%.0f KB, library + %d font files)"
          % (os.path.getsize(OUT) / 1024, n))
    print("Commit bundle.zip and lib/ - the deployed site loads them directly.")


if __name__ == "__main__":
    main()
