"""Synthetic Backblaze raw CSV fixtures for offline prepare_data tests."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from benchmark.backblaze_hdd.prepare_data import SMART_COLS, quarter_bounds, quarter_dirname

MODEL_ST = "ST8000DM002"
MODEL_TOSHIBA = "TOSHIBA MG07ACA12TEY"
MODEL_WDC = "WDC WD30EZRX"


def _capacity(model: str) -> int:
    if model.startswith("ST"):
        return int(8e12)
    if "MG07" in model:
        return int(12e12)
    return int(3e12)


def make_tiny_raw(
    raw_dir: Path,
    quarters: list[str],
    n_stay: int = 40,
    n_fail: int = 12,
    n_small: int = 4,
    seed: int = 0,
) -> dict:
    raw_dir = raw_dir.resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)
    serials_by_quarter: dict[str, list[str]] = {}
    fail_date_by_serial: dict[str, date] = {}

    cross_serial = f"cross-{seed}"
    rng = 0

    for qi, quarter in enumerate(quarters):
        q_start, q_end = quarter_bounds(quarter)
        days = (q_end - q_start).days + 1
        qdir = raw_dir / quarter_dirname(quarter)
        qdir.mkdir(parents=True, exist_ok=True)

        serials: list[str] = [cross_serial]
        for i in range(n_stay):
            serials.append(f"stay-{seed}-{qi}-{i}")
        for i in range(n_fail):
            serials.append(f"fail-{seed}-{qi}-{i}")
        for i in range(n_small):
            serials.append(f"small-{seed}-{qi}-{i}")
        serials_by_quarter[quarter] = serials

        fail_indices = list(range(n_fail))
        for idx, sn in enumerate(serials):
            if sn == cross_serial and qi > 0:
                model = MODEL_ST
            elif sn.startswith("small"):
                model = MODEL_WDC
            elif sn.startswith("fail"):
                model = MODEL_ST if idx % 2 == 0 else MODEL_TOSHIBA
            else:
                model = MODEL_ST if idx % 3 else MODEL_TOSHIBA

            cap = _capacity(model)
            fail_day_offset = None
            if sn.startswith("fail"):
                fi = fail_indices.pop(0)
                fail_day_offset = int(days * (fi + 1) / (n_fail + 1))
                fail_date = q_start + timedelta(days=fail_day_offset)
                fail_date_by_serial[sn] = fail_date

            rows: list[dict] = []
            for d in range(days):
                cur = q_start + timedelta(days=d)
                if fail_day_offset is not None and d > fail_day_offset:
                    break
                failure = "1" if fail_day_offset is not None and d == fail_day_offset else "0"
                row = {
                    "date": cur.isoformat(),
                    "serial_number": sn,
                    "model": model,
                    "capacity_bytes": str(cap),
                    "failure": failure,
                }
                for col in SMART_COLS:
                    base = int(hashlib.md5(f"{sn}-{col}-{d}".encode()).hexdigest()[:6], 16) % 100
                    if sn.startswith("fail") and col == "smart_197_raw" and fail_day_offset is not None:
                        if fail_day_offset - 7 <= d <= fail_day_offset:
                            base += d - fail_day_offset + 7
                    row[col] = str(base)
                row["smart_255_raw"] = "0"
                rows.append(row)

            file_idx = int(hashlib.md5(sn.encode()).hexdigest()[:2], 16) % 2
            out_path = qdir / f"part{file_idx}_{sn}.csv"
            pd.DataFrame(rows).to_csv(out_path, index=False)
            rng += 1

    return {"serials_by_quarter": serials_by_quarter, "fail_date_by_serial": fail_date_by_serial}
