"""Give one SmartMem candidate a public view of a prepared run directory, run it, keep its output.

Three commitments shape this file. A candidate is untrusted code, so it runs in its own child
process, inside a directory this call created and hands back destroyed, with anything that looks
like a credential wiped from its environment and its captured output cut off at a fixed size. What
it sees is only the public snapshot the task contract describes - the training rows without their
labels beside a separate label file, the scored rows without either - because a candidate that
could read another split's ``split_key`` could score itself. And nothing here scores anything: the
label join and the metric stay in ``evaluator.py``, on the trusted side of the line this file draws.

A real serial number is a device identifier. It is written into the snapshot the candidate reads on
this machine, and it is redacted from every string this file returns, because those strings go into
evolution logs.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

SNAPSHOT_VERSION = "smartmem-snapshot-v1"

#: The four files one split's public snapshot holds, named exactly as ``problem.md`` section 1
#: names them, because that text is what a candidate's author reads before writing any code.
TRAIN_SAMPLES = "train_samples.csv.gz"
TRAIN_LABELS = "train_labels.csv"
#: Columns a candidate must never receive: the outcome it is scored on, and the split a row belongs
#: to, which would tell it how many rows it owes predictions for and which window each sits in.
WITHHELD_COLUMNS = ("label", "split_key")
INDEX_COLUMNS = ("sample_id", "unit_id", "prediction_time", "history_end", "serial_number_type")
OUTPUT_COLUMNS = ("sample_id", "score", "alarm")
#: The queue a unit lands in when the side table does not declare its type - the same reading the
#: evaluator uses, so a candidate and the scorer never disagree about what a row said.
UNKNOWN_TYPE = "unknown"

MAX_CAPTURED_CHARS = 20000
#: Any name that suggests a secret is dropped from the child's environment. A candidate has no
#: business reading one, and a value echoed into its stdout would end up in an evolution log.
SECRET_NAME_HINTS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "SSH",
    "AUTH",
    "DASHSCOPE",
    "AWS",
)
#: A serial number as it appears in the event data, matched only to keep it out of a log.
SERIAL_IN_TEXT = re.compile(r"sn_\d+")


class SnapshotError(ValueError):
    """A run directory that cannot produce the public snapshot a candidate needs."""


@dataclass(frozen=True)
class CandidateRun:
    """What one child process left behind: how it ended, what it said, and whether it wrote."""

    returncode: int
    timed_out: bool
    duration: float
    output_tail: str
    prediction_path: Path | None


def _sample_rows(run_dir: Path) -> pd.DataFrame:
    """Read every sample partition of a run directory, keys, labels and features together."""
    directory = Path(run_dir) / "partitions" / "samples"
    files = sorted(path for path in directory.glob("*") if path.is_file())
    if not files:
        raise SnapshotError(
            f"{directory} holds no sample partition, so there is nothing to hand a candidate; run "
            "prepare_data.py in sample mode first"
        )
    frame = pd.concat([pd.read_csv(path) for path in files], ignore_index=True)
    needed = ("sample_id", "unit_id", "prediction_time", "history_end") + WITHHELD_COLUMNS
    missing = [column for column in needed if column not in frame.columns]
    if missing:
        raise SnapshotError(
            f"the sample partitions do not carry {', '.join(missing)}; a snapshot cannot be built "
            "from a table that cannot say which row a prediction was made on"
        )
    duplicated = int(frame["sample_id"].duplicated().sum())
    if duplicated:
        raise SnapshotError(
            f"{duplicated} sample_id value(s) appear on more than one row, so a candidate's "
            "prediction would join to two anchors at once; rebuild the run directory"
        )
    return frame


def _unit_types(run_dir: Path) -> pd.Series:
    """Map each unit to its declared queue; empty when the side table is missing."""
    path = Path(run_dir).joinpath("partitions", "units", "serial_type")
    if not path.is_file():
        return pd.Series(dtype="object")
    table = pd.read_csv(path)
    absent = [column for column in ("unit_id", "serial_number_type") if column not in table]
    if absent:
        raise SnapshotError(
            f"{path} has no {', '.join(absent)} column, so the index could not name each row's "
            "queue; rebuild the run directory with a current prepare_data.py"
        )
    named = table.dropna(subset=["serial_number_type"]).drop_duplicates(subset=["unit_id"])
    pairs = zip(named["unit_id"].astype(str), named["serial_number_type"].astype(str))
    return pd.Series(dict(pairs))


def public_snapshot(run_dir: Path, split: str, dest: Path) -> Path:
    """Write the four public files for one split and hand back the directory holding them.

    The training half keeps its labels only in ``train_labels.csv``, and the scored half carries no
    label at all: that asymmetry is the whole point of the snapshot, and it is why the labels never
    leave the directory this function writes into.
    """
    rows = _sample_rows(run_dir)
    split_keys = rows["split_key"].astype(str)
    train = rows.loc[split_keys == "train"]
    query = rows.loc[split_keys == split]
    if train.empty:
        raise SnapshotError(
            "the run directory holds no row with split_key 'train', so a candidate would have "
            "nothing to fit on; ask for a directory prepare_data.py split by time"
        )
    if query.empty:
        available = ", ".join(sorted(set(split_keys)))
        raise SnapshotError(
            f"the run directory holds no row with split_key {split!r} (it has {available}), so "
            "there is no slice to hand a candidate"
        )
    types = _unit_types(run_dir)
    destination = Path(dest)
    destination.mkdir(parents=True, exist_ok=True)
    train.drop(columns=list(WITHHELD_COLUMNS)).to_csv(destination / TRAIN_SAMPLES, index=False)
    train.loc[:, ["sample_id", "label"]].to_csv(destination / TRAIN_LABELS, index=False)
    index = query.loc[:, list(INDEX_COLUMNS[:-1])].copy()
    index["serial_number_type"] = (
        index["unit_id"].astype(str).map(types).fillna(UNKNOWN_TYPE).astype(str)
    )
    index.to_csv(destination / f"{split}_index.csv", index=False)
    visible = query.drop(columns=list(WITHHELD_COLUMNS))
    visible.to_csv(destination / f"{split}_samples.csv.gz", index=False)
    return destination


def _child_env() -> dict[str, str]:
    """The parent's environment minus anything that names a credential."""
    env = {}
    for name, value in os.environ.items():
        if any(hint in name.upper() for hint in SECRET_NAME_HINTS):
            continue
        env[name] = value
    return env


def _tail(text: str) -> str:
    """The last stretch of a candidate's output, serial numbers gone, size bounded."""
    cleaned = SERIAL_IN_TEXT.sub("[unit]", text or "")
    return cleaned[-MAX_CAPTURED_CHARS:]


def execute(
    program: Path, data_dir: Path, split: str, out_path: Path, timeout: int = 900
) -> CandidateRun:
    """Run one candidate as a child process on the contract's own command line.

    ``sys.executable`` and an argument list, never a shell string: a candidate's file name is not
    something this process should be interpreting. The instant it returns, the caller owns the
    answer - including a timeout, which is a result here rather than an exception, because a
    candidate that ran too long is a scoring outcome the evolution loop has to record.
    """
    command = [
        sys.executable,
        str(Path(program).resolve()),
        "--data-dir",
        str(Path(data_dir).resolve()),
        "--split",
        str(split),
        "--out",
        str(Path(out_path).resolve()),
    ]
    started = time.monotonic()
    try:
        process = subprocess.run(
            command,
            cwd=str(Path(data_dir).resolve()),
            env=_child_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        captured = " ".join(part for part in (exc.stdout, exc.stderr) if isinstance(part, str))
        return CandidateRun(
            returncode=-1,
            timed_out=True,
            duration=round(time.monotonic() - started, 3),
            output_tail=_tail(captured),
            prediction_path=None,
        )
    duration = round(time.monotonic() - started, 3)
    produced = Path(out_path)
    return CandidateRun(
        returncode=int(process.returncode),
        timed_out=False,
        duration=duration,
        output_tail=_tail((process.stderr or "") + (process.stdout or "")),
        prediction_path=produced if produced.is_file() else None,
    )


__all__ = [
    "CandidateRun",
    "INDEX_COLUMNS",
    "OUTPUT_COLUMNS",
    "SNAPSHOT_VERSION",
    "SnapshotError",
    "TRAIN_LABELS",
    "TRAIN_SAMPLES",
    "WITHHELD_COLUMNS",
    "execute",
    "public_snapshot",
]
