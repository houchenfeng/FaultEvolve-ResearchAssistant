#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from faultevolve.discovery.report import build_manifest, verify_md


def main() -> int:
    md_path = Path(sys.argv[1])
    art = Path(sys.argv[2])
    run_id = art.name
    manifest = build_manifest(art, run_id)
    md = md_path.read_text(encoding="utf-8")
    bad = verify_md(md, manifest)
    if bad:
        print(json.dumps({"ok": False, "mismatches": bad}))
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
