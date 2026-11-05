"""V1-06 (part 1): the run manifest - opaque input identity, config hash, atomic resume.

Nothing in this module may write a source file name, because a file name can be a real serial
number. The manifest therefore identifies inputs by content digest and partitions by the opaque
name the caller chose, and every checkpoint is written ``.tmp`` first and renamed only after the
output hash was taken.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest

from faultevolve.data.manifest import (
    MANIFEST_VERSION,
    ConfigChangedError,
    ManifestError,
    config_hash,
    finish_partition,
    input_digests,
    plan_resume,
    prepare_run,
    read_manifest,
    sha256_file,
    verify_partitions,
    writer_lock,
)

ALGORITHM = "prep-v1"
CONFIG = {"lookback": "5 days", "lead": "15 minutes", "horizon": "7 days", "seed": 7}


def write_raw(tmp_path: Path, name: str = "unit-file.csv", text: str = "a,b\n1,2\n") -> Path:
    """A raw file whose *name* looks like an identifier; the manifest must never echo it."""
    path = tmp_path / "raw" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def started(tmp_path: Path, *, paths: list[Path] | None = None, config: dict | None = None):
    raw = write_raw(tmp_path) if paths is None else None
    out = tmp_path / "out"
    manifest = prepare_run(
        out,
        raw_dir=tmp_path / "raw",
        paths=paths if paths is not None else [raw],
        config=config if config is not None else CONFIG,
        algorithm_version=ALGORITHM,
    )
    return out, manifest


# ---------------------------------------------------------------- input identity


def test_a_file_digests_to_its_bytes_in_spite_of_the_chunked_read(tmp_path):
    path = write_raw(tmp_path, text="x" * (3 * 1024 * 1024))
    import hashlib

    assert sha256_file(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_input_digests_are_sorted_content_hashes_and_carry_no_names(tmp_path):
    first = write_raw(tmp_path, "aa.csv", "1\n")
    second = write_raw(tmp_path, "zz.csv", "2\n")
    digests = input_digests([second, first])
    assert digests == sorted([sha256_file(first), sha256_file(second)])
    assert all(len(d) == 64 for d in digests)


def test_two_files_with_the_same_content_are_two_inputs(tmp_path):
    a = write_raw(tmp_path, "a.csv", "same\n")
    b = tmp_path / "raw" / "b.csv"
    b.write_text("same\n", encoding="utf-8")
    digests = input_digests([a, b])
    assert len(digests) == 2  # the manifest counts files, not distinct content
    assert len(set(digests)) == 1


def test_a_missing_input_file_is_reported_without_a_stack_of_paths(tmp_path):
    with pytest.raises(ManifestError, match="does not exist"):
        sha256_file(tmp_path / "raw" / "gone.csv")


# ---------------------------------------------------------------- config hash


def test_the_config_hash_ignores_key_order_but_not_values():
    shuffled = {"seed": 7, "horizon": "7 days", "lead": "15 minutes", "lookback": "5 days"}
    assert config_hash(shuffled, algorithm_version=ALGORITHM) == config_hash(
        CONFIG, algorithm_version=ALGORITHM
    )
    assert config_hash({**CONFIG, "seed": 8}, algorithm_version=ALGORITHM) != config_hash(
        CONFIG, algorithm_version=ALGORITHM
    )


def test_the_algorithm_version_is_part_of_the_hash():
    assert config_hash(CONFIG, algorithm_version="prep-v2") != config_hash(
        CONFIG, algorithm_version=ALGORITHM
    )


def test_the_manifest_states_which_contract_produced_it(tmp_path):
    _, manifest = started(tmp_path)
    assert manifest["manifest_version"] == MANIFEST_VERSION
    assert manifest["algorithm_version"] == ALGORITHM


def test_non_json_values_are_refused_instead_of_stringified():
    with pytest.raises(ManifestError, match="lookback"):
        config_hash({"lookback": pd.Timedelta(days=5)}, algorithm_version=ALGORITHM)


def test_not_a_number_is_refused_because_json_would_write_invalid_output():
    with pytest.raises(ManifestError, match="not a finite number"):
        config_hash({"seed": float("nan")}, algorithm_version=ALGORITHM)


def test_a_private_path_or_credential_in_the_config_is_refused():
    for payload in (
        {"raw": "C:\\Users\\someone\\data\\raw"},
        {"raw": "/home/someone/data/raw"},
        {"dashscope_api_key": "whatever"},
    ):
        with pytest.raises(ManifestError):
            config_hash(payload, algorithm_version=ALGORITHM)


def test_nested_config_dicts_are_hashed_stably():
    deep_a = {"windows": {"lead": "15 minutes", "horizon": "7 days"}, "seed": 1}
    deep_b = {"seed": 1, "windows": {"horizon": "7 days", "lead": "15 minutes"}}
    assert config_hash(deep_a, algorithm_version=ALGORITHM) == config_hash(
        deep_b, algorithm_version=ALGORITHM
    )


# ---------------------------------------------------------------- run directory


def test_prepare_run_writes_a_manifest_that_names_no_input_file(tmp_path):
    out, manifest = started(tmp_path)
    assert (out / "manifest.json").is_file()
    text = (out / "manifest.json").read_text(encoding="utf-8")
    assert "unit-file" not in text
    assert manifest["inputs"]["count"] == 1
    assert manifest["partitions"] == {}


def test_preparing_the_same_run_again_reuses_the_manifest(tmp_path):
    _, first = started(tmp_path)
    finish_partition(
        tmp_path / "out",
        name="train/part-000",
        path=_partition_file(tmp_path, "train/part-000"),
        rows=3,
    )
    again = prepare_run(
        tmp_path / "out",
        raw_dir=tmp_path / "raw",
        paths=[write_raw(tmp_path)],
        config=CONFIG,
        algorithm_version=ALGORITHM,
    )
    assert again["config_hash"] == first["config_hash"]
    assert list(again["partitions"]) == ["train/part-000"]  # reuse does not erase progress


def _partition_file(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "out" / "partitions" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("sample_id\nabc\n", encoding="utf-8")
    return path


def test_a_pre_existing_directory_without_a_manifest_is_not_overwritten(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "someone_elses.csv").write_text("keep me\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="no manifest"):
        prepare_run(
            out,
            raw_dir=tmp_path / "raw",
            paths=[write_raw(tmp_path)],
            config=CONFIG,
            algorithm_version=ALGORITHM,
        )
    assert (out / "someone_elses.csv").is_file()


def test_a_truncated_manifest_is_refused(tmp_path):
    out, _ = started(tmp_path)
    (out / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError, match="manifest"):
        read_manifest(out)


def test_the_raw_directory_and_the_output_directory_may_not_contain_each_other(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for out in (raw, raw / "out", tmp_path):
        with pytest.raises(ManifestError, match="inside|same directory"):
            prepare_run(
                out,
                raw_dir=raw,
                paths=[write_raw(tmp_path)],
                config=CONFIG,
                algorithm_version=ALGORITHM,
            )


# ---------------------------------------------------------------- partitions and resume


def test_a_finished_partition_records_its_own_output_hash(tmp_path):
    out, _ = started(tmp_path)
    path = _partition_file(tmp_path, "train/part-000")
    entry = finish_partition(out, name="train/part-000", path=path, rows=3)
    assert entry["sha256"] == sha256_file(path)
    assert entry["rows"] == 3
    assert entry["status"] == "complete"
    assert read_manifest(out)["partitions"]["train/part-000"]["sha256"] == entry["sha256"]


def test_a_leftover_tmp_file_never_counts_as_a_finished_partition(tmp_path):
    out, _ = started(tmp_path)
    finish_partition(
        out, name="train/part-000", path=_partition_file(tmp_path, "train/part-000"), rows=3
    )
    dangling = out / "partitions" / "dev" / "part-000.csv.tmp"
    dangling.parent.mkdir(parents=True, exist_ok=True)
    dangling.write_text("half written\n", encoding="utf-8")
    manifest = read_manifest(out)
    assert list(manifest["partitions"]) == ["train/part-000"]
    plan = plan_resume(
        out,
        paths=[write_raw(tmp_path)],
        config=CONFIG,
        algorithm_version=ALGORITHM,
    )
    assert plan["rebuild"] == []  # a .tmp is not a partition the run promised to produce


def test_resume_reuses_everything_when_nothing_changed(tmp_path):
    out, _ = started(tmp_path)
    finish_partition(
        out, name="train/part-000", path=_partition_file(tmp_path, "train/part-000"), rows=3
    )
    plan = plan_resume(
        out,
        paths=[write_raw(tmp_path)],
        config=CONFIG,
        algorithm_version=ALGORITHM,
    )
    assert plan["reuse"] == ["train/part-000"]
    assert plan["rebuild"] == []
    assert plan["reason"] is None


def test_a_changed_config_exits_with_the_dedicated_code(tmp_path):
    out, _ = started(tmp_path)
    with pytest.raises(ConfigChangedError) as caught:
        plan_resume(
            out,
            paths=[write_raw(tmp_path)],
            config={**CONFIG, "seed": 8},
            algorithm_version=ALGORITHM,
        )
    assert caught.value.exit_code == 2


def test_a_changed_seed_is_a_config_change_not_a_new_dataset(tmp_path):
    out, _ = started(tmp_path)
    with pytest.raises(ConfigChangedError):
        plan_resume(
            out,
            paths=[write_raw(tmp_path)],
            config={**CONFIG, "seed": 9},
            algorithm_version=ALGORITHM,
        )


def test_modified_input_content_rebuilds_every_partition(tmp_path):
    out, _ = started(tmp_path)
    path = _partition_file(tmp_path, "train/part-000")
    finish_partition(out, name="train/part-000", path=path, rows=3)
    raw = write_raw(tmp_path, text="a,b\n9,9\n")  # the same file name, different content
    plan = plan_resume(
        out,
        paths=[raw],
        config=CONFIG,
        algorithm_version=ALGORITHM,
    )
    assert plan["reason"] == "inputs"
    assert plan["rebuild"] == ["train/part-000"]
    assert plan["reuse"] == []


def test_a_single_damaged_partition_is_the_only_one_rebuilt(tmp_path):
    out, _ = started(tmp_path)
    good = _partition_file(tmp_path, "train/part-000")
    finish_partition(out, name="train/part-000", path=good, rows=3)
    other = _partition_file(tmp_path, "dev/part-000")
    finish_partition(out, name="dev/part-000", path=other, rows=2)
    other.write_text("sample_id\nrot\n", encoding="utf-8")  # silent damage on disk
    damaged = verify_partitions(out)
    assert damaged["corrupt"] == ["dev/part-000"]
    assert damaged["ok"] == ["train/part-000"]
    plan = plan_resume(
        out,
        paths=[write_raw(tmp_path)],
        config=CONFIG,
        algorithm_version=ALGORITHM,
    )
    assert plan["reason"] == "outputs"
    assert plan["rebuild"] == ["dev/part-000"]


def test_a_deleted_partition_file_is_rebuilt_not_rehashed(tmp_path):
    out, _ = started(tmp_path)
    path = _partition_file(tmp_path, "train/part-000")
    finish_partition(out, name="train/part-000", path=path, rows=3)
    path.unlink()
    damaged = verify_partitions(out)
    assert damaged["missing"] == ["train/part-000"]
    assert damaged["corrupt"] == []


def test_a_partition_name_cannot_escape_the_output_directory(tmp_path):
    out, _ = started(tmp_path)
    with pytest.raises(ManifestError, match="partition name"):
        finish_partition(
            out, name="../escape", path=_partition_file(tmp_path, "train/part-001"), rows=1
        )


def test_only_one_coordinator_may_write_a_run_directory(tmp_path):
    out, _ = started(tmp_path)
    with writer_lock(out, owner="run-1"):
        with pytest.raises(ManifestError, match="another writer"):
            with writer_lock(out, owner="run-2"):
                pass
    with writer_lock(out, owner="run-3"):
        assert read_manifest(out)["manifest_version"] == MANIFEST_VERSION


def test_the_writer_lock_is_removed_after_a_clean_exit(tmp_path):
    out, _ = started(tmp_path)
    with writer_lock(out, owner="run-1"):
        pass
    assert not (out / "writer.lock").exists()


def test_the_manifest_layer_carries_no_domain_vocabulary():
    root = Path(__file__).resolve().parents[1] / "src" / "faultevolve" / "data"
    for name in ("manifest.py", "__init__.py"):
        source = (root / name).read_text(encoding="utf-8")
        banned = re.findall(r"\b(DIMM|mcelog|ECC|UE|bankid|SmartMem)\b", source, re.IGNORECASE)
        assert banned == [], f"{name} leaked domain vocabulary: {banned}"
