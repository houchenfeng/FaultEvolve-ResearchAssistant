"""V1-06 (part 2b): partition writing - one coordinator, independent worker files, real resume.

The requirement this part is written against is the resume one: a rerun must be able to tell
"reuse", "rebuild this partition" and "rebuild everything" apart, and a worker must never be able to
stamp a partition complete before its bytes were hashed. So the workers write only their own output
file, and the coordinator - the one holding the writer lock - is the only thing that touches the
manifest.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pytest

from faultevolve.data.io import IoError, PartitionJob, write_partitions
from faultevolve.data.manifest import (
    MANIFEST_VERSION,
    ManifestError,
    plan_resume,
    prepare_run,
    read_manifest,
    verify_partitions,
    writer_lock,
)

ALGORITHM = "prep-v1"
CONFIG = {"lookback": "5 days", "lead": "15 minutes", "seed": 7}


def raw_file(tmp_path: Path, name: str = "unit-file.csv", text: str = "a,b\n1,2\n") -> Path:
    path = tmp_path / "raw" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def started(tmp_path: Path, name: str = "out") -> Path:
    out = tmp_path / name
    prepare_run(
        out,
        raw_dir=tmp_path / "raw",
        paths=[raw_file(tmp_path)],
        config=CONFIG,
        algorithm_version=ALGORITHM,
    )
    return out


@dataclass
class Builder:
    """Counts how often a partition was actually produced, which is what makes reuse testable."""

    rows: int = 3
    calls: list[str] = field(default_factory=list)
    fail_once: str | None = None

    def job(self, name: str) -> PartitionJob:
        def build() -> pd.DataFrame:
            if self.fail_once == name and name not in self.calls:
                self.calls.append(name)
                raise OSError(
                    f"disk full while writing {self.secret_path}"
                )
            self.calls.append(name)
            return pd.DataFrame(
                {
                    "sample_id": [f"{name}-{index}" for index in range(self.rows)],
                    "value": list(range(self.rows)),
                }
            )

        return PartitionJob(name=name, build=build)

    secret_path = "/home/someone/raw/unit-serial-123456.csv"


def partitions(out: Path) -> Path:
    return out / "partitions"


# ------------------------------------------------------------------ happy path


def test_writing_partitions_records_every_partition_in_the_manifest(tmp_path):
    out = started(tmp_path)
    builder = Builder()
    report = write_partitions(
        out,
        [builder.job("train/part-000"), builder.job("train/part-001")],
        workers=1,
        owner="run-1",
    )
    assert report["written"] == ["train/part-000", "train/part-001"]
    assert report["reused"] == [] and report["failed"] == []
    manifest = read_manifest(out)
    assert manifest["partitions"]["train/part-000"]["rows"] == 3
    assert (partitions(out) / "train/part-000").is_file()


def test_a_partition_file_is_written_before_it_is_checkpointed(tmp_path):
    out = started(tmp_path)
    builder = Builder()
    write_partitions(out, [builder.job("train/part-000")], workers=1, owner="run-1")
    written = partitions(out) / "train/part-000"
    entry = read_manifest(out)["partitions"]["train/part-000"]
    assert entry["sha256"] == hashlib.sha256(written.read_bytes()).hexdigest()
    assert not list(out.rglob("*.tmp"))


def test_the_output_of_a_partition_is_the_frame_the_job_built(tmp_path):
    out = started(tmp_path)
    write_partitions(
        out, [Builder(rows=2).job("dev/part-000")], workers=1, owner="run-1"
    )
    back = pd.read_csv(partitions(out) / "dev/part-000", dtype=str, keep_default_na=False)
    assert back["sample_id"].tolist() == ["dev/part-000-0", "dev/part-000-1"]


# ------------------------------------------------------------------ workers


def test_one_worker_and_two_workers_produce_the_same_partitions(tmp_path):
    names = [f"train/part-{index:03d}" for index in range(4)]
    digests: list[dict[str, str]] = []
    for workers in (1, 2):
        out = started(tmp_path, name=f"out-{workers}")
        builder = Builder()
        report = write_partitions(
            out, [builder.job(name) for name in names], workers=workers, owner=f"run-{workers}"
        )
        assert report["written"] == sorted(names)
        assert sorted(builder.calls) == names
        digests.append(
            {name: entry["sha256"] for name, entry in read_manifest(out)["partitions"].items()}
        )
    assert digests[0] == digests[1]


def test_two_workers_produce_two_partitions_at_the_same_time(tmp_path):
    out = started(tmp_path)
    # A barrier makes this a claim about concurrency rather than about wall-clock time: a build that
    # ran one partition at a time could never find its partner already waiting.
    barrier = threading.Barrier(2, timeout=10)

    def job(name: str) -> PartitionJob:
        def build() -> pd.DataFrame:
            barrier.wait()
            return pd.DataFrame({"sample_id": [name], "value": [0]})

        return PartitionJob(name=name, build=build)

    report = write_partitions(
        out, [job("train/part-000"), job("train/part-001")], workers=2, owner="run-1"
    )
    assert report["written"] == ["train/part-000", "train/part-001"]
    assert report["failed"] == []


def test_a_worker_count_that_is_not_positive_is_refused(tmp_path):
    out = started(tmp_path)
    with pytest.raises(IoError, match="workers"):
        write_partitions(out, [Builder().job("train/part-000")], workers=0, owner="run-1")


def test_a_partition_name_cannot_escape_the_run_directory(tmp_path):
    out = started(tmp_path)
    builder = Builder()
    with pytest.raises(ManifestError, match="partition name"):
        write_partitions(out, [builder.job("../escape")], workers=1, owner="run-1")
    # Refusing at the checkpoint would be too late: the file and the build would already have
    # happened, so the names are validated before a single partition is produced.
    assert builder.calls == []
    assert not list(out.rglob("*escape*"))
    assert read_manifest(out)["partitions"] == {}


def test_only_one_coordinator_may_write_partitions_at_a_time(tmp_path):
    out = started(tmp_path)
    with writer_lock(out, owner="run-1"):
        with pytest.raises(ManifestError, match="another writer"):
            write_partitions(out, [Builder().job("train/part-000")], workers=2, owner="run-2")


def test_two_jobs_cannot_write_the_same_partition(tmp_path):
    out = started(tmp_path)
    builder = Builder()
    with pytest.raises(IoError, match="two jobs"):
        write_partitions(
            out,
            [builder.job("train/part-000"), builder.job("train/part-000")],
            workers=2,
            owner="run-1",
        )
    assert builder.calls == []


def test_a_worker_that_crashes_after_writing_leaves_no_temp_file(tmp_path):
    out = started(tmp_path)
    # A directory sitting where the partition file belongs is what makes a worker fail after it
    # opened its temp file: the bytes are written, then the rename into place is refused.
    (partitions(out) / "train" / "part-000").mkdir(parents=True)
    report = write_partitions(
        out, [Builder().job("train/part-000")], workers=1, owner="run-1"
    )
    assert [entry["name"] for entry in report["failed"]] == ["train/part-000"]
    assert report["written"] == []
    assert not list(out.rglob("*.tmp")), "a crashed worker must remove the temp file it wrote"
    assert "train/part-000" not in read_manifest(out)["partitions"]


def test_a_run_directory_with_no_manifest_is_refused(tmp_path):
    out = tmp_path / "out"
    out.mkdir(parents=True)
    with pytest.raises(ManifestError, match="no manifest"):
        write_partitions(out, [Builder().job("train/part-000")], workers=1, owner="run-1")


# ------------------------------------------------------------------ resume


def test_a_failed_partition_is_reported_without_renaming_its_error_message(tmp_path):
    out = started(tmp_path)
    builder = Builder(fail_once="train/part-001")
    report = write_partitions(
        out,
        [builder.job("train/part-000"), builder.job("train/part-001")],
        workers=1,
        owner="run-1",
    )
    assert report["written"] == ["train/part-000"]
    assert [entry["name"] for entry in report["failed"]] == ["train/part-001"]
    assert "unit-serial-123456" not in str(report)
    assert "home/someone" not in str(report)
    assert "train/part-001" not in read_manifest(out)["partitions"]
    assert not (partitions(out) / "train/part-001").exists()
    assert not list(out.rglob("*.tmp")), "a failed worker must clean up its own temp file"


def test_an_interrupted_run_rebuilds_only_what_was_never_finished(tmp_path):
    out = started(tmp_path)
    names = [f"train/part-{index:03d}" for index in range(3)]
    broken = Builder(fail_once="train/part-002")
    write_partitions(out, [broken.job(name) for name in names], workers=1, owner="run-1")
    assert broken.calls == ["train/part-000", "train/part-001", "train/part-002"]

    fixed = Builder()
    report = write_partitions(
        out, [fixed.job(name) for name in names], workers=1, owner="run-1"
    )
    assert report["reused"] == ["train/part-000", "train/part-001"]
    assert report["written"] == ["train/part-002"]
    assert fixed.calls == ["train/part-002"], "a reused partition must not be produced again"
    assert sorted(read_manifest(out)["partitions"]) == names


def test_a_damaged_partition_is_the_only_one_rebuilt_on_a_rerun(tmp_path):
    out = started(tmp_path)
    names = [f"train/part-{index:03d}" for index in range(3)]
    write_partitions(
        out, [Builder().job(name) for name in names], workers=1, owner="run-1"
    )
    damaged = partitions(out) / "train/part-001"
    damaged.write_bytes(b"truncated by an interrupted copy")

    builder = Builder()
    report = write_partitions(
        out, [builder.job(name) for name in names], workers=1, owner="run-1"
    )
    assert report["written"] == ["train/part-001"]
    assert report["reused"] == ["train/part-000", "train/part-002"]
    assert builder.calls == ["train/part-001"]
    assert verify_partitions(out)["corrupt"] == []


def test_resume_advice_and_the_writer_agree_about_what_to_rebuild(tmp_path):
    out = started(tmp_path)
    names = [f"train/part-{index:03d}" for index in range(3)]
    write_partitions(
        out, [Builder().job(name) for name in names], workers=1, owner="run-1"
    )
    (partitions(out) / "train/part-000").unlink()
    advice = plan_resume(
        out, paths=[raw_file(tmp_path)], config=CONFIG, algorithm_version=ALGORITHM
    )
    assert advice["rebuild"] == ["train/part-000"]
    builder = Builder()
    report = write_partitions(
        out, [builder.job(name) for name in names], workers=1, owner="run-1"
    )
    assert report["written"] == advice["rebuild"]
    assert builder.calls == ["train/part-000"]


def test_a_changed_config_stops_a_rerun_before_any_partition_is_produced(tmp_path):
    out = started(tmp_path)
    builder = Builder()
    with pytest.raises(ManifestError, match="config differs"):
        write_partitions(
            out,
            [builder.job("train/part-000")],
            workers=1,
            owner="run-1",
            config={"lookback": "3 days", "lead": "15 minutes", "seed": 7},
            algorithm_version=ALGORITHM,
        )
    assert builder.calls == []


def test_a_changed_input_content_stops_a_rerun_before_any_partition_is_produced(tmp_path):
    out = started(tmp_path)
    other = raw_file(tmp_path, name="other-input.csv", text="a,b\n9,9\n")
    builder = Builder()
    with pytest.raises(ManifestError, match="input files differ"):
        write_partitions(
            out,
            [builder.job("train/part-000")],
            workers=1,
            owner="run-1",
            paths=[other],
            config=CONFIG,
            algorithm_version=ALGORITHM,
        )
    assert builder.calls == []


def test_a_reused_partition_is_checked_by_hash_not_by_mere_existence(tmp_path):
    out = started(tmp_path)
    names = ["train/part-000", "train/part-001"]
    write_partitions(out, [Builder().job(name) for name in names], workers=1, owner="run-1")
    (partitions(out) / "train/part-000").write_text("a,b\n9,9\n", encoding="utf-8")
    builder = Builder()
    report = write_partitions(out, [builder.job(name) for name in names], workers=1, owner="run-1")
    assert report["written"] == ["train/part-000"]
    assert builder.calls == ["train/part-000"]


def test_the_manifest_is_the_only_record_of_who_wrote_what(tmp_path):
    out = started(tmp_path)
    write_partitions(out, [Builder().job("train/part-000")], workers=1, owner="run-1")
    text = (out / "manifest.json").read_text(encoding="utf-8")
    assert MANIFEST_VERSION in text
    assert "unit-file" not in text
    assert "someone" not in text and "serial" not in text
