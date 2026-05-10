#!/usr/bin/env python3
"""Build base.en.lmo from base.en.po using SuperFastHash-based LMO format."""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(__file__))

import po2lmo

PO_FILE = os.path.join(BASE_DIR, "i18n", "base.en.po")
LMO_FILE = os.path.join(BASE_DIR, "i18n", "base.en.lmo")


def build():
    if not os.path.exists(PO_FILE):
        print(f"ERROR: {PO_FILE} not found. Run gen_po.py first.")
        sys.exit(1)

    lmo = po2lmo.Lmo(verbose=1)
    lmo.load_from_text(PO_FILE)
    buf = lmo.save_to_bin(LMO_FILE)
    size_kb = len(buf) / 1024
    print(f"LMO built: {LMO_FILE} ({size_kb:.1f} KB, {len(lmo.entries)} entries)")


if __name__ == "__main__":
    build()
