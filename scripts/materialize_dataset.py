"""Materialize a manifest into FaultEvolve's stable per-device input contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from faultevolve.data.universal_adapter import materialize_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="JSON manifest describing telemetry and events")
    parser.add_argument("output_dir", type=Path, help="directory for the normalized cache")
    args = parser.parse_args()
    result = materialize_dataset(args.manifest, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
