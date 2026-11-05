#!/usr/bin/env python
"""Export the front-end contract from the Python source of truth (TODO §1.4).

Writes four files under ``web/openapi/``:

* ``faultevolve.openapi.json``    -- the FastAPI schema, i.e. every DTO
* ``evolve-config.schema.json``   -- ``EvolveConfig.model_json_schema()``
* ``engine-catalog.json``         -- enums, adapters, event types, field lists
* ``ui-metadata.json``            -- Chinese labels / grouping / advanced flags

Guarantees: the script never starts a server, never touches run artifacts and
never reads anything under a ``holdout`` directory. Output is byte-stable so CI
can diff it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

OPENAPI_DIR = REPO_ROOT / "web" / "openapi"

from faultevolve.config import EvolveConfig  # noqa: E402
from faultevolve.webapi.app import create_app  # noqa: E402
from faultevolve.webapi.catalog import (  # noqa: E402
    build_engine_catalog,
    build_ui_metadata,
)

#: Output file name -> builder. Order is stable so the summary reads the same
#: way every time.
CONTRACT_FILES: tuple[tuple[str, str], ...] = (
    ("faultevolve.openapi.json", "openapi"),
    ("evolve-config.schema.json", "config_schema"),
    ("engine-catalog.json", "engine_catalog"),
    ("ui-metadata.json", "ui_metadata"),
)


def render(payload: Any) -> str:
    """Stable JSON text: sorted keys, 2-space indent, unescaped CJK, trailing LF."""
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_all() -> dict[str, str]:
    """Return ``{filename: json_text}`` for every contract file."""
    app = create_app()
    payloads: dict[str, Any] = {
        "openapi": app.openapi(),
        "config_schema": EvolveConfig.model_json_schema(),
        "engine_catalog": build_engine_catalog(),
        "ui_metadata": build_ui_metadata(),
    }
    return {name: render(payloads[key]) for name, key in CONTRACT_FILES}


def write_all(target_dir: Path = OPENAPI_DIR) -> list[Path]:
    """Write every contract file and return the paths written."""
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, text in build_all().items():
        path = target_dir / name
        # newline="" so Windows never rewrites LF into CRLF: these files are
        # diffed by check_web_contracts.py.
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        written.append(path)
    return written


def main() -> int:
    written = write_all()
    print(f"exported {len(written)} contract files into {OPENAPI_DIR}")
    for path in written:
        size = path.stat().st_size
        print(f"  {path.name:<32}{size:>8} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
