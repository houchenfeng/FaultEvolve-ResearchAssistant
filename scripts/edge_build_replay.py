#!/usr/bin/env python
"""生成平板数据中心孪生的回放数据（edge-tablet/public/replay.json）。

从公开 val 切分随机抽取一个"机房"：N 块盘的 14 天 SMART 窗口，其中 K 块是
标签为"截止日后 7 天内故障"的真实故障盘。每块盘的窗口被对齐到相对日 1..14
（第 14 天即截止日）；故障发生在第 15..21 天中的某一天——标签只说明 7 天内
故障，具体哪天由固定种子模拟。抽样只用随机种子，不按任何模型的结果挑盘。
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "benchmark" / "hdd_mvp" / "data"
OUT = REPO / "edge-tablet" / "public" / "replay.json"
HISTORY_DAYS = 14
HORIZON_DAYS = 7
RACKS = 10
SLOTS_PER_RACK = 30


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--disks", type=int, default=RACKS * SLOTS_PER_RACK)
    ap.add_argument("--failing", type=int, default=10)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    meta = json.loads((DATA / "meta.json").read_text("utf-8"))
    columns: list[str] = meta["smart_columns"]
    index = pd.read_csv(DATA / "public" / "val_index.csv", parse_dates=["cutoff_date"])
    labels = pd.read_csv(DATA / "eval_only" / "val_labels.csv")[["serial_number", "label"]]
    index = index.merge(labels, on="serial_number")

    rng = np.random.default_rng(args.seed)
    pos = index[index["label"] == 1]
    neg = index[index["label"] == 0]
    chosen = pd.concat([
        pos.iloc[rng.choice(len(pos), args.failing, replace=False)],
        neg.iloc[rng.choice(len(neg), args.disks - args.failing, replace=False)],
    ])
    chosen = chosen.iloc[rng.permutation(len(chosen))].reset_index(drop=True)

    wanted = set(chosen["serial_number"])
    hist = pd.read_csv(
        DATA / "public" / "val_history.csv.gz",
        usecols=["date", "serial_number", "capacity_bytes", *columns],
        parse_dates=["date"],
    )
    hist = hist[hist["serial_number"].isin(wanted)]
    by_serial = {sn: g for sn, g in hist.groupby("serial_number")}

    disks = []
    for i, row in chosen.iterrows():
        sn = row["serial_number"]
        g = by_serial.get(sn)
        days: list[list[float | None] | None] = [None] * HISTORY_DAYS
        capacity = 0.0
        if g is not None:
            for _, snap in g.iterrows():
                offset = (row["cutoff_date"] - snap["date"]).days
                if 0 <= offset < HISTORY_DAYS:
                    vals = []
                    for c in columns:
                        v = snap[c]
                        vals.append(None if (v is None or (isinstance(v, float) and math.isnan(v))) else round(float(v), 3))
                    days[HISTORY_DAYS - 1 - offset] = vals
            capacity = float(g["capacity_bytes"].max())
        fail_day = int(HISTORY_DAYS + rng.integers(1, HORIZON_DAYS + 1)) if row["label"] == 1 else None
        disks.append({
            "sn": sn,
            "model": row["model"],
            "cap": capacity,
            "rack": int(i // SLOTS_PER_RACK),
            "slot": int(i % SLOTS_PER_RACK),
            "fail_day": fail_day,
            "days": days,
        })

    payload = {
        "version": 1,
        "seed": args.seed,
        "source": "Backblaze 公开 val 切分（benchmark/hdd_mvp）；故障日在标签给出的 7 天窗口内按种子模拟",
        "history_days": HISTORY_DAYS,
        "horizon_days": HORIZON_DAYS,
        "racks": RACKS,
        "slots_per_rack": SLOTS_PER_RACK,
        "start_date": "2026-11-01",
        "columns": columns,
        "disks": disks,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "utf-8")
    failing = [d["sn"] for d in disks if d["fail_day"] is not None]
    print(f"wrote {args.out} ({args.out.stat().st_size / 1024:.0f} KB): {len(disks)} disks, failing={failing}")


if __name__ == "__main__":
    main()
