"""Download Backblaze Drive Stats quarterly CSV archives (stdlib only)."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_BASE = "https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data"
_QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$")


def parse_quarter(s: str) -> tuple[int, int]:
    m = _QUARTER_RE.match(s)
    if not m:
        raise ValueError(f"invalid quarter: {s}")
    return int(m.group(1)), int(m.group(2))


def quarter_dirname(s: str) -> str:
    y, q = parse_quarter(s)
    return f"data_Q{q}_{y}"


def zip_url(s: str, base_url: str = DEFAULT_BASE) -> str:
    y, q = parse_quarter(s)
    return f"{base_url}/data_Q{q}_{y}.zip"


def plan_downloads(quarters: list[str], raw_dir: Path, base_url: str = DEFAULT_BASE) -> list[dict]:
    raw_dir = raw_dir.resolve()
    plans: list[dict] = []
    for q in quarters:
        extract_dir = raw_dir / quarter_dirname(q)
        skip = extract_dir.exists() and any(extract_dir.glob("*.csv"))
        plans.append(
            {
                "quarter": q,
                "url": zip_url(q, base_url=base_url),
                "zip_path": raw_dir / f"{quarter_dirname(q)}.zip",
                "extract_dir": extract_dir,
                "skip": skip,
            }
        )
    return plans


def extract_zip(zip_path: Path, raw_dir: Path, quarter: str) -> Path:
    dest = raw_dir / quarter_dirname(quarter)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if member.startswith("__MACOSX/"):
                continue
            name = Path(member)
            if ".." in name.parts or name.is_absolute():
                raise ValueError(f"unsafe zip member path: {member}")
            if not member.lower().endswith(".csv"):
                continue
            target = dest / Path(member).name
            with zf.open(member) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
    return dest


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, part)
    part.replace(dest)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quarters", nargs="+", required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-zip", action="store_true")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    args = ap.parse_args(argv)

    plans = plan_downloads(args.quarters, args.raw_dir, base_url=args.base_url)
    for plan in plans:
        print(f"{plan['url']} -> {plan['zip_path']} -> {plan['extract_dir']}", flush=True)
        if args.dry_run or plan["skip"]:
            continue
        download(plan["url"], plan["zip_path"])
        extract_zip(plan["zip_path"], args.raw_dir, plan["quarter"])
        if not args.keep_zip:
            plan["zip_path"].unlink(missing_ok=True)


if __name__ == "__main__":
    main(sys.argv[1:])
