"""V1-07: benchmark/smartmem/prepare_data.py - the pipeline that ties the data layer together.

The contract tested here is the one the plan's section 7 states: exit codes 0/1/2/3 mean four
different things, ``--json`` puts exactly one object on stdout while progress goes to stderr, and
nothing a real deployment would consider private - a unit identifier, a raw row, a credential - may
appear in either stream.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.smartmem import prepare_data as prep  # noqa: E402
from faultevolve.data.external_sort import (  # noqa: E402
    MERGED_FILE_NAME,
    RUNS_DIR_NAME,
    SORT_SIDECAR_NAME,
    SortError,
)
from faultevolve.data.manifest import read_manifest  # noqa: E402
from faultevolve.tasks.smartmem_data import (  # noqa: E402
    FEATURE_MANIFEST,
    SERIAL_COLUMN,
    UNIT_TYPE_COLUMNS,
    anonymize_unit,
    read_smartmem_file,
    render_policy_fingerprint,
    unit_from_filename,
)
from helpers_smartmem import (  # noqa: E402
    EVENTS_BY_UNIT,
    FAILURE_TIME_BY_UNIT,
    SENTINEL_UNIT,
    SERIAL_TYPE_BY_UNIT,
    write_fixture,
)

BOUNDS = {
    "start": "2024-01-01",
    "train_until": "2024-03-01",
    "dev_until": "2024-03-20",
    "val_until": "2024-04-08",
    "outcome_observed_until": "2024-04-30",
}
UNIT_COUNT = 9


def raw_dir(
    tmp_path: Path,
    *,
    fmt: str = "csv",
    typed_statics: bool = False,
    rebuild: bool = True,
) -> Path:
    if not rebuild and (tmp_path / "raw" / "train").is_dir():
        return tmp_path / "raw"
    return write_fixture(tmp_path / "raw", fmt=fmt, typed_statics=typed_statics)


def split_config(tmp_path: Path, name: str = "split.yaml", **overrides: str) -> str:
    body = dict(BOUNDS)
    body.update(overrides)
    path = tmp_path / name
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return str(path)


def argv(
    tmp_path: Path,
    *,
    options: dict[str, str] | None = None,
    flags: tuple[str, ...] = (),
    out_name: str = "out",
    config: bool = True,
    rebuild: bool = True,
    fmt: str = "csv",
    typed_statics: bool = False,
) -> list[str]:
    # rebuild=False keeps the fixture a previous run saw, so a test can damage it on purpose.
    raw = raw_dir(tmp_path, fmt=fmt, typed_statics=typed_statics, rebuild=rebuild)
    out = tmp_path / out_name
    words = ["--raw-dir", str(raw), "--out-dir", str(out), "--format", fmt, "--timezone", "UTC"]
    if config:
        words += ["--split-config", split_config(tmp_path)]
    for name, value in (options or {}).items():
        words += [name] if value == "" else [name, str(value)]
    words += list(flags)
    return words


# --------------------------------------------------------------------- exit codes


def test_a_small_fixture_prepares_samples_and_records_them(tmp_path, capsys):
    code = prep.main(argv(tmp_path))
    assert code == prep.EXIT_OK
    manifest = read_manifest(tmp_path / "out")
    assert any(name.startswith("samples/") for name in manifest["partitions"])
    assert "audit/summary" in manifest["partitions"]
    assert (tmp_path / "out" / "partitions" / "samples").is_dir()
    text = capsys.readouterr().out
    assert SENTINEL_UNIT not in text
    # human mode is a summary, not a JSON blob: a reader should see words, not braces
    assert not text.lstrip().startswith("{")
    assert "sample partition" in text


def test_an_unknown_format_is_an_input_error_and_creates_nothing(tmp_path):
    code = prep.main(argv(tmp_path, options={"--format": "parquet"}))
    assert code == prep.EXIT_INPUT
    assert not (tmp_path / "out").exists()


def test_missing_time_bounds_stop_the_run_and_name_the_missing_items(tmp_path, capsys):
    code = prep.main(argv(tmp_path, config=False))
    assert code == prep.EXIT_INPUT
    message = capsys.readouterr().err
    assert "--split-config" in message
    for item in ("train_until", "dev_until", "val_until", "outcome_observed_until"):
        assert item in message


def test_a_val_split_that_outruns_the_follow_up_is_refused(tmp_path, capsys):
    config = split_config(
        tmp_path,
        name="late.yaml",
        val_until="2024-04-29",
        outcome_observed_until="2024-04-30",
    )
    code = prep.main(argv(tmp_path, options={"--split-config": config}))
    assert code == prep.EXIT_INPUT
    assert "coverage ends" in capsys.readouterr().err
    assert not (tmp_path / "out" / "manifest.json").exists()


def test_a_frontier_past_the_last_ticket_reports_the_rows_it_invents_as_negatives(tmp_path, capsys):
    """The audit is green in this case on purpose: it checks leakage, not what the tickets cover.

    Measured on 200 real units, 1 866 of 19 540 sample rows (9.5%) were anchored after the newest
    alarm and every one of them carried label 0. The fixture reproduces the shape - a frontier a
    month past the last ticket - so the run has to name the gap instead of leaving it in a document.
    """
    code = prep.main(argv(tmp_path, flags=("--json",)))
    assert code == prep.EXIT_OK
    coverage = json.loads(capsys.readouterr().out)["coverage"]
    assert coverage["ticket_coverage_end"] == "2024-04-07T12:00:00.000000001+00:00"
    assert coverage["outcome_observed_until"] == "2024-04-30T00:00:00+00:00"
    assert coverage["rows_beyond_coverage"] == 6


def test_a_frontier_inside_ticket_coverage_reports_no_invented_negatives(tmp_path, capsys):
    """The report follows the input; a run whose frontier the tickets do cover says so."""
    config = split_config(
        tmp_path,
        name="tight.yaml",
        val_until="2024-03-30",
        outcome_observed_until="2024-04-07",
    )
    code = prep.main(
        argv(tmp_path, options={"--split-config": config}, out_name="out_tight", flags=("--json",))
    )
    assert code == prep.EXIT_OK
    assert json.loads(capsys.readouterr().out)["coverage"]["rows_beyond_coverage"] == 0


def test_the_coverage_gap_is_spoken_in_the_human_summary_and_names_no_unit(tmp_path, capsys):
    assert prep.main(argv(tmp_path)) == prep.EXIT_OK
    text = capsys.readouterr().out
    assert "anchored later" in text
    for unit in EVENTS_BY_UNIT:
        assert unit not in text


def test_an_epoch_number_in_the_split_config_is_not_guessed(tmp_path, capsys):
    config = split_config(tmp_path, name="epoch.yaml", train_until="1709251200")
    code = prep.main(argv(tmp_path, options={"--split-config": config}))
    assert code == prep.EXIT_INPUT
    assert "epoch" in capsys.readouterr().err


def test_an_unknown_timezone_stops_rather_than_defaulting_to_utc(tmp_path):
    code = prep.main(argv(tmp_path, options={"--timezone": "Mars/Olympus"}))
    assert code == prep.EXIT_INPUT


def test_a_unit_listed_twice_stops_before_any_partition_is_planned(tmp_path, capsys):
    raw = raw_dir(tmp_path)
    queue = raw / "type_A"
    queue.mkdir()
    for name in ("unit-clean", "unit-lead-hit"):
        shutil.copy(raw / "train" / f"{name}.csv", queue / f"{name}.csv")
    code = prep.main(argv(tmp_path, options={"--raw-dir": str(raw)}))
    assert code == prep.EXIT_INPUT
    assert "listed twice" in capsys.readouterr().err


def test_a_changed_config_on_a_resume_exits_two(tmp_path):
    assert prep.main(argv(tmp_path)) == prep.EXIT_OK
    second = argv(tmp_path, options={"--lookback-days": "4"}, flags=("--resume",), out_name="out")
    assert prep.main(second) == prep.EXIT_CONFIG


def test_a_changed_rendering_policy_stops_a_resume(tmp_path, monkeypatch):
    """The dtype policy has to be inside the hash, or an old out dir resumes as if it were current.

    Two renderings under one ``config_hash`` is the failure the fingerprint exists to catch: the
    resume path trusts that hash and reuses partitions it never saw being written.
    """
    assert prep.main(argv(tmp_path)) == prep.EXIT_OK
    monkeypatch.setattr(prep, "render_policy_fingerprint", lambda **kw: "0" * 64)
    second = argv(tmp_path, flags=("--resume",), out_name="out")
    assert prep.main(second) == prep.EXIT_CONFIG


def test_the_rendering_fingerprint_follows_the_declaration():
    baseline = render_policy_fingerprint()
    assert len(baseline) == 64
    assert baseline == render_policy_fingerprint(FEATURE_MANIFEST)

    moved = dict(FEATURE_MANIFEST)
    moved["FrequencyMHz"] = {**moved["FrequencyMHz"], "dtype": "float64"}
    assert render_policy_fingerprint(moved) != baseline

    renamed = {k: v for k, v in FEATURE_MANIFEST.items() if k != "FrequencyMHz"}
    assert render_policy_fingerprint(renamed) != baseline


def test_the_rendering_fingerprint_follows_the_policy_version(monkeypatch):
    import faultevolve.tasks.smartmem_data as smd

    baseline = render_policy_fingerprint()
    monkeypatch.setattr(smd, "RENDER_POLICY_VERSION", "smartmem-render-v2")
    assert render_policy_fingerprint() != baseline


def test_feather_is_a_declared_dependency_not_a_local_accident():
    """``--format feather`` is advertised, so the reader has to ship with the package.

    It lived only in one hand-built venv on one laptop, which is how a fresh machine finds out the
    hard way - on Linux, after the long run has already started.
    """
    body = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    project = body.split("[project]", 1)[1].split("[project.optional-dependencies]", 1)[0]
    assert re.search(r'^\s*"pyarrow', project, re.M), project


def test_a_recorded_run_directory_needs_resume_to_be_reused(tmp_path, capsys):
    assert prep.main(argv(tmp_path)) == prep.EXIT_OK
    capsys.readouterr()
    assert prep.main(argv(tmp_path)) == prep.EXIT_INPUT
    assert "--resume" in capsys.readouterr().err


def test_a_different_unit_listing_stops_a_resume(tmp_path):
    """The cheap fingerprint has to cover which units exist, or a plan describes another dataset."""
    raw = raw_dir(tmp_path)
    assert prep.main(argv(tmp_path)) == prep.EXIT_OK
    (raw / "train" / "unit-static-late.csv").unlink()
    second = argv(tmp_path, flags=("--resume",), rebuild=False)
    assert prep.main(second) == prep.EXIT_CONFIG


def tamper_one_file(raw: Path, *, keep_size: bool) -> None:
    """Rewrite one event row so the bytes say something different than the run recorded."""
    target = raw / "train" / "unit-clean.csv"
    data = target.read_bytes()
    swapped = data.replace(b",ce,", b",ue,", 1)
    assert swapped != data
    if keep_size:
        assert len(swapped) == len(data)
        target.write_bytes(swapped)
        return
    target.write_bytes(swapped + b"1\n")


def test_hash_inputs_notices_a_same_size_edit_of_an_event_file(tmp_path):
    raw = raw_dir(tmp_path)
    assert prep.main(argv(tmp_path, flags=("--hash-inputs",))) == prep.EXIT_OK
    tamper_one_file(raw, keep_size=True)
    second = argv(tmp_path, flags=("--hash-inputs", "--resume"), rebuild=False)
    assert prep.main(second) == prep.EXIT_INPUT


def test_the_listing_fingerprint_notices_a_changed_file_without_hashing(tmp_path):
    """The cheap guard is name plus size, which is what makes a 130 GB resume affordable.

    ``--hash-inputs`` is the strict mode; without it a same-size byte edit is not detected at all,
    which the test above deliberately does not pretend otherwise about.
    """
    raw = raw_dir(tmp_path)
    assert prep.main(argv(tmp_path)) == prep.EXIT_OK
    tamper_one_file(raw, keep_size=False)
    second = argv(tmp_path, flags=("--resume",), rebuild=False)
    assert prep.main(second) == prep.EXIT_CONFIG


def test_cold_units_are_withheld_from_train(tmp_path, capsys):
    code = prep.main(
        argv(tmp_path, options={"--cold-unit-fraction": "0.2", "--json": ""}),
    )
    assert code == prep.EXIT_OK
    audit = json.loads(capsys.readouterr().out)["audit"]
    assert audit["cold_units"] == 2
    assert audit["splits"].get("cold_audit", 0) > 0


def test_a_failing_unit_exits_three_and_reports_only_the_partition_name(tmp_path, capsys):
    real = prep.read_smartmem_file

    def flaky(path, **kwargs):
        if "unit-static-late" in Path(path).name:
            raise OSError("simulated read failure")
        return real(path, **kwargs)

    capsys.readouterr()
    prep.read_smartmem_file = flaky
    try:
        code = prep.main(argv(tmp_path, options={"--units-per-partition": "1", "--json": ""}))
    finally:
        prep.read_smartmem_file = real
    assert code == prep.EXIT_PARTIAL
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == prep.EXIT_PARTIAL
    assert len(payload["failed"]) == 1
    assert re.fullmatch(r"samples/part-\d{5}", payload["failed"][0]["name"])
    assert all("unit-static-late" not in json.dumps(entry) for entry in payload["failed"])
    manifest = read_manifest(tmp_path / "out")
    assert "audit/summary" not in manifest["partitions"]
    assert len([name for name in manifest["partitions"] if name.startswith("samples/")]) == 8


def test_an_audit_violation_is_not_a_successful_run(tmp_path, monkeypatch):
    real = prep.assign_temporal_splits

    def wrong(frame, boundaries, **kwargs):
        marked = real(frame, boundaries, **kwargs)
        if len(marked):
            marked.loc[marked.index[:1], "split_key"] = "nonsense"
        return marked

    monkeypatch.setattr(prep, "assign_temporal_splits", wrong)
    assert prep.main(argv(tmp_path)) == prep.EXIT_INPUT


# --------------------------------------------------------------------- modes


def test_dry_run_plans_without_writing_a_run_directory(tmp_path, capsys):
    code = prep.main(argv(tmp_path, options={"--json": ""}, flags=("--dry-run",), config=False))
    assert code == prep.EXIT_OK
    assert not (tmp_path / "out" / "manifest.json").exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload["files"] == UNIT_COUNT
    assert payload["partitions"] >= 1
    assert payload["suggested_bounds"]["train_end"]


def test_profile_only_writes_the_profile_and_no_samples(tmp_path):
    # the fixture spells its types in lowercase, so it declares them rather than inheriting the
    # default, which describes the shipped package
    code = prep.main(
        argv(tmp_path, options={"--error-types": "ce,ue"}, flags=("--profile-only",))
    )
    assert code == prep.EXIT_OK
    recorded = read_manifest(tmp_path / "out")["partitions"]
    assert list(recorded) == ["profile"]


def test_resume_reuses_partitions_whose_hash_still_matches(tmp_path, capsys):
    # the second run raises --workers: how a run happens is not part of what a partition holds,
    # so a wider machine must reuse the previous outputs instead of looking like a new experiment
    assert prep.main(argv(tmp_path)) == prep.EXIT_OK
    recorded = read_manifest(tmp_path / "out")["partitions"]
    written = sorted(name for name in recorded if not name.startswith("audit/"))
    capsys.readouterr()
    code = prep.main(
        argv(tmp_path, options={"--json": "", "--workers": "2"}, flags=("--resume",))
    )
    assert code == prep.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["written"] == []
    assert payload["reused"] == written
    assert prep.UNIT_TYPE_PARTITION in written


# --------------------------------------------------------------------- output shape


def test_json_mode_writes_exactly_one_object_to_stdout(tmp_path, capsys):
    code = prep.main(argv(tmp_path, options={"--json": "", "--workers": "2"}))
    assert code == prep.EXIT_OK
    captured = capsys.readouterr()
    text = captured.out.strip()
    assert text.startswith("{") and text.endswith("}")
    payload = json.loads(text)
    assert payload["exit_code"] == 0 and payload["audit"]["passed"] is True
    assert SENTINEL_UNIT not in text and SENTINEL_UNIT not in captured.err


def test_max_files_limits_what_is_read(tmp_path, capsys):
    code = prep.main(
        argv(tmp_path, options={"--max-files": "2", "--json": "", "--dry-run": ""})
    )
    assert code == prep.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["files"] == 2
    assert payload["partitions"] == 1


def test_a_truncated_slice_reports_an_empty_split_rather_than_passing(tmp_path, capsys):
    # --max-files is a smoke knob, so a truncated slice must fail the audit instead of quietly
    # scoring a split that holds two units.
    code = prep.main(argv(tmp_path, options={"--max-files": "2"}))
    assert code == prep.EXIT_INPUT
    assert "empty_split" in capsys.readouterr().err


def test_a_declared_space_floor_is_enforced_before_anything_is_written(tmp_path, capsys):
    code = prep.main(argv(tmp_path, options={"--min-free-gb": "1000000"}))
    assert code == prep.EXIT_INPUT
    assert "free" in capsys.readouterr().err
    assert not (tmp_path / "out" / "manifest.json").exists()


def test_the_worker_count_changes_nothing_about_the_bytes_written(tmp_path, capsys):
    """Determinism, proven in two run directories: one worker and two must agree digest for digest.

    Re-running the same directory would test the resume path, not the writer, so the two runs are
    deliberately kept apart.
    """
    raw = raw_dir(tmp_path)
    config = split_config(tmp_path)
    codes = []
    for name in ("one", "two"):
        capsys.readouterr()
        codes.append(
            prep.main(
                [
                    "--raw-dir", str(raw),
                    "--out-dir", str(tmp_path / name),
                    "--format", "csv",
                    "--timezone", "UTC",
                    "--split-config", config,
                    "--workers", "2" if name == "two" else "1",
                ]
            )
        )
    assert codes == [prep.EXIT_OK, prep.EXIT_OK]
    first = read_manifest(tmp_path / "one")["partitions"]
    second = read_manifest(tmp_path / "two")["partitions"]
    assert sorted(first) == sorted(second)
    assert [first[name]["sha256"] for name in sorted(first)] == [
        second[name]["sha256"] for name in sorted(second)
    ]


def test_the_manifest_names_no_unit(tmp_path):
    assert prep.main(argv(tmp_path, options={"--units-per-partition": "1"})) == prep.EXIT_OK
    text = (tmp_path / "out" / "manifest.json").read_text(encoding="utf-8")
    assert SENTINEL_UNIT not in text
    assert "unit-" not in text


def test_list_mcelog_files_finds_the_queue_directories_of_the_real_layout(tmp_path):
    root = tmp_path / "raw_tmp"
    for queue in ("type_A", "type_B"):
        directory = root / queue
        directory.mkdir(parents=True)
        pd.DataFrame({"log_time": [1], "rowid": [1]}).to_feather(directory / "unit-0001.feather")
    files = prep.list_mcelog_files(root, "feather")
    assert [path.parent.name for path in files] == ["type_A", "type_B"]


# --------------------------------------------------------------- --sort-inputs (V1-06 part 2e)


def sort_argv(
    tmp_path: Path,
    *,
    options: dict[str, str] | None = None,
    flags: tuple[str, ...] = (),
    sort_dir: str | None = "sorted",
    rebuild: bool = True,
    fmt: str = "csv",
    typed_statics: bool = False,
) -> list[str]:
    """The same invocation shape as ``argv``, for the mode that only sorts."""
    raw = raw_dir(tmp_path, fmt=fmt, typed_statics=typed_statics, rebuild=rebuild)
    words = [
        "--raw-dir",
        str(raw),
        "--out-dir",
        str(tmp_path / "out"),
        "--format",
        fmt,
        "--timezone",
        "UTC",
        "--sort-inputs",
    ]
    if sort_dir is not None:
        words += ["--sort-dir", str(tmp_path / sort_dir)]
    for name, value in (options or {}).items():
        words += [name] if value == "" else [name, str(value)]
    words += list(flags)
    return words


def source_rows(raw: Path) -> dict[str, int]:
    """Rows the domain reader keeps per unit, which is the number a sort must reproduce."""
    return {
        path.name: len(read_smartmem_file(path, fmt="csv", timezone="UTC"))
        for path in sorted((raw / "train").glob("*.csv"))
    }


def disk_times(path: Path) -> list[str]:
    """The instants as they sit on disk, which is the only place the disorder still exists.

    :func:`read_smartmem_file` sorts what it returns, so asking it whether an input is unordered
    can never answer yes; the raw read is what a unit file's on-disk order means.
    """
    return [str(value) for value in pd.read_csv(path)["log_time"]]


def test_sorting_a_fixture_tree_produces_one_ordered_file_per_unit(tmp_path, capsys):
    code = prep.main(sort_argv(tmp_path))
    assert code == prep.EXIT_OK
    workspaces = sorted((tmp_path / "sorted" / "train").iterdir())
    assert len(workspaces) == UNIT_COUNT
    times = []
    for workspace in workspaces:
        merged = workspace / MERGED_FILE_NAME
        assert merged.is_file()
        assert (workspace / SORT_SIDECAR_NAME).is_file()
        assert not (workspace / RUNS_DIR_NAME).exists()
        frame = pd.read_csv(merged)
        stamps = pd.to_datetime(frame["log_time"], utc=True)
        times.append((int(len(frame)), bool((stamps.diff().dropna() >= pd.Timedelta(0)).all())))
    assert all(ordered for _, ordered in times), "a sorted file is still out of order"
    expected = source_rows(tmp_path / "raw")
    assert sum(rows for rows, _ in times) == sum(expected.values())


def test_the_fixture_ships_disorder_and_the_sort_is_measured_against_it(tmp_path):
    """A green sort over already-sorted inputs would prove nothing.

    The fixture writes ``unit-dup-events`` in a scrambled disk order on purpose, so this asserts
    that the disorder is still there and that the file which carries it comes out ordered.
    """
    raw = raw_dir(tmp_path / "probe")
    unordered = [
        path
        for path in sorted((raw / "train").glob("*.csv"))
        if (times := disk_times(path)) != sorted(times)
    ]
    assert unordered, "the fixture no longer ships an out-of-order unit file"
    assert prep.main(sort_argv(tmp_path, sort_dir="sorted_probe")) == prep.EXIT_OK
    for path in unordered:
        unit = unit_from_filename(path)
        merged = (
            tmp_path
            / "sorted_probe"
            / "train"
            / anonymize_unit(unit)
            / MERGED_FILE_NAME
        )
        frame = pd.read_csv(merged)
        stamps = pd.to_datetime(frame["log_time"], utc=True)
        assert (stamps.diff().dropna() >= pd.Timedelta(0)).all(), f"{path.name} stayed unordered"
        # The workspace directory is named by a hash, so the sorted rows are the only place this
        # unit still identifies itself; a sort that lost the column would be unreadable downstream.
        assert set(frame[SERIAL_COLUMN].unique()) == {unit}, path.name


def test_the_sort_writes_a_layout_the_next_step_can_read(tmp_path):
    code = prep.main(sort_argv(tmp_path))
    assert code == prep.EXIT_OK
    layout = pd.read_csv(tmp_path / "sorted" / "layout.csv")
    assert list(layout.columns) == [
        "queue",
        "unit",
        "workspace",
        "rows",
        "runs",
        "reused",
        "source_bytes",
    ]
    assert len(layout) == UNIT_COUNT
    assert set(layout["queue"]) == {"train"}
    inputs = tmp_path / "raw" / "train"
    assert int(layout["source_bytes"].sum()) == sum(
        path.stat().st_size for path in inputs.glob("*.csv")
    )
    assert int(layout["rows"].sum()) == sum(source_rows(tmp_path / "raw").values())
    text = (tmp_path / "sorted" / "layout.csv").read_text(encoding="utf-8")
    assert str(tmp_path / "raw") not in text and "unit-" not in text
    # Relative and resolvable: a ledger of absolute paths would be a different machine's tree,
    # and a row naming a workspace that does not exist would send the next step looking for nothing.
    sort_dir = tmp_path / "sorted"
    for _, row in layout.iterrows():
        workspace = Path(str(row["workspace"]))
        assert not workspace.is_absolute(), workspace
        assert (sort_dir / workspace / MERGED_FILE_NAME).is_file(), workspace


def test_a_dry_run_reports_the_space_without_touching_the_disk(tmp_path, capsys):
    code = prep.main(sort_argv(tmp_path, options={"--json": "", "--dry-run": ""}))
    assert code == prep.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "sort-inputs"
    assert payload["files"] == UNIT_COUNT
    inputs = (tmp_path / "raw" / "train").glob("*.csv")
    source_bytes = sum(path.stat().st_size for path in inputs)
    # More than the inputs themselves: the estimate has to cover the runs, the widest merge and
    # the merged output, or the number would not be a warning about a full disk.
    assert payload["space"]["needed_bytes"] > source_bytes
    assert payload["space"]["sufficient"] is True
    assert not (tmp_path / "sorted").exists()


def test_a_unit_listed_twice_stops_the_sort_too(tmp_path, capsys):
    """Two files for one unit would sort into two workspaces that each claim to be its history.

    ``layout.csv`` keys on the unit, so the duplicate has to stop the run rather than become two
    rows a later step cannot join on.
    """
    raw = raw_dir(tmp_path)
    queue = raw / "type_A"
    queue.mkdir()
    for name in ("unit-clean", "unit-lead-hit"):
        shutil.copy(raw / "train" / f"{name}.csv", queue / f"{name}.csv")
    code = prep.main(sort_argv(tmp_path, rebuild=False))
    assert code == prep.EXIT_INPUT
    assert "listed twice" in capsys.readouterr().err
    assert not (tmp_path / "sorted").exists()


def test_a_dry_run_reports_a_tight_volume_instead_of_refusing(
    tmp_path, capsys, monkeypatch
):
    """A plan has to describe a full disk, not stop on it, or it cannot be used to size one.

    The real run of the same numbers refuses; only the dry run gets to report ``sufficient: False``
    and stay successful, which is why the report is checked before the refusal.
    """
    probe = prep.main(sort_argv(tmp_path, options={"--json": "", "--dry-run": ""}))
    assert probe == prep.EXIT_OK
    needed = json.loads(capsys.readouterr().out)["space"]["needed_bytes"]
    monkeypatch.setattr(
        prep.shutil, "disk_usage", lambda path: type("U", (), {"free": needed - 456})()
    )
    code = prep.main(
        sort_argv(tmp_path, sort_dir="sorted_tight", options={"--json": "", "--dry-run": ""})
    )
    assert code == prep.EXIT_OK
    space = json.loads(capsys.readouterr().out)["space"]
    assert space["needed_bytes"] == needed
    assert space["free_bytes"] == needed - 456
    assert space["shortfall_bytes"] == 456
    assert space["sufficient"] is False
    assert not (tmp_path / "sorted_tight").exists()


def test_a_mode_that_needs_a_run_directory_says_so(tmp_path, capsys):
    """``--sort-inputs`` is the only reason ``--out-dir`` is optional, so the omission needs a name.

    argparse's own usage error exits 2, which in this CLI means "the config changed", so the guard
    reports through exit 1 instead - and a test has to tell those two apart, or the message could
    be argparse's usage dump.
    """
    raw = raw_dir(tmp_path)
    code = prep.main(
        [
            "--raw-dir",
            str(raw),
            "--format",
            "csv",
            "--timezone",
            "UTC",
            "--split-config",
            split_config(tmp_path),
            "--dry-run",
        ]
    )
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    assert "--out-dir is required" in err
    assert "usage:" not in err


def test_an_insufficient_volume_is_refused_before_a_workspace_exists(
    tmp_path, capsys, monkeypatch
):
    probe = prep.main(sort_argv(tmp_path, options={"--json": "", "--dry-run": ""}))
    assert probe == prep.EXIT_OK
    needed = json.loads(capsys.readouterr().out)["space"]["needed_bytes"]
    monkeypatch.setattr(
        prep.shutil, "disk_usage", lambda path: type("U", (), {"free": needed - 1})()
    )
    code = prep.main(sort_argv(tmp_path, sort_dir="sorted_tight", options={"--json": ""}))
    assert code == prep.EXIT_INPUT
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == prep.EXIT_INPUT
    assert str(needed) in payload["error"]
    assert not (tmp_path / "sorted_tight").exists()


def test_the_free_space_is_read_from_the_volume_being_written(tmp_path, capsys, monkeypatch):
    """The volume under ``--sort-dir``, not the one under the raw tree.

    A report about the wrong volume would tell an operator to move the output when the input was
    already on a full disk, so the two numbers have to be distinguishable - which is what the
    stand-in below arranges. The sort directory does not exist during a dry run, so the honest probe
    walks up to its nearest existing ancestor, and that ancestor is the volume being asked about.
    """
    sort_dir = tmp_path / "sorted"

    def probe(path):
        record = type("U", (), {})()
        record.total = 10_000
        record.used = 5_000
        record.free = 111 if Path(path) == sort_dir.parent else 999
        return record

    monkeypatch.setattr(prep.shutil, "disk_usage", probe)
    code = prep.main(sort_argv(tmp_path, options={"--json": "", "--dry-run": ""}))
    assert code == prep.EXIT_OK
    space = json.loads(capsys.readouterr().out)["space"]
    assert space["free_bytes"] == 111


def test_sorting_twice_reuses_every_workspace_and_keeps_the_bytes(tmp_path, capsys):
    assert prep.main(sort_argv(tmp_path)) == prep.EXIT_OK
    workspace = next((tmp_path / "sorted" / "train").iterdir())
    before = (workspace / MERGED_FILE_NAME).read_bytes()
    capsys.readouterr()
    code = prep.main(sort_argv(tmp_path, rebuild=False, options={"--json": ""}))
    assert code == prep.EXIT_OK
    assert (workspace / MERGED_FILE_NAME).read_bytes() == before
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"] == sum(source_rows(tmp_path / "raw").values())
    assert payload["reused"] == UNIT_COUNT
    layout = pd.read_csv(tmp_path / "sorted" / "layout.csv")
    assert bool(layout["reused"].all())


def test_sort_mode_needs_a_directory_of_its_own(tmp_path, capsys):
    code = prep.main(sort_argv(tmp_path, sort_dir=None))
    assert code == prep.EXIT_INPUT
    assert "required with --sort-inputs" in capsys.readouterr().err


def test_the_sort_directory_may_not_live_inside_the_raw_tree(tmp_path, capsys):
    code = prep.main(sort_argv(tmp_path, sort_dir="raw/inside"))
    assert code == prep.EXIT_INPUT
    # Distinctive wording only, so the test cannot pass on argparse's "unrecognized arguments"
    # usage dump, which quotes every flag name including these.
    err = capsys.readouterr().err
    assert "inside" in err.lower()
    assert not (tmp_path / "raw" / "inside").exists()


def test_sort_mode_and_profile_mode_are_exclusive(tmp_path, capsys):
    code = prep.main(sort_argv(tmp_path, flags=("--profile-only",)))
    assert code == prep.EXIT_INPUT
    assert "one mode at a time" in capsys.readouterr().err


def test_a_sort_failure_reports_its_type_and_not_a_traceback(tmp_path, capsys, monkeypatch):
    def refuse(*args, **kwargs):
        raise SortError("the runtime directory already holds 1 entry this sort did not produce")

    monkeypatch.setattr(prep, "sort_file_to_time_order", refuse)
    (tmp_path / "sorted" / "train").mkdir(parents=True)
    (tmp_path / "sorted" / "train" / "foreign.txt").write_text("x", encoding="utf-8")
    code = prep.main(sort_argv(tmp_path))
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    assert "SortError" in err and "Traceback" not in err


# ------------------------------------------------- --from-sorted (V1-06 part 2f)


def sorted_tree(
    tmp_path: Path,
    *,
    name: str = "sorted",
    fmt: str = "csv",
    typed_statics: bool = False,
    rebuild: bool = True,
) -> Path:
    """Produce the tree the consume mode reads, so no test hand-writes a derived artefact."""
    assert prep.main(
        sort_argv(tmp_path, sort_dir=name, fmt=fmt, typed_statics=typed_statics, rebuild=rebuild)
    ) == prep.EXIT_OK
    return tmp_path / name


def consume_argv(
    tmp_path: Path,
    tree: Path,
    *,
    options: dict[str, str] | None = None,
    flags: tuple[str, ...] = (),
    out_name: str = "out",
    fmt: str = "csv",
    typed_statics: bool = False,
) -> list[str]:
    """``argv`` for the mode that reads events from a sorted tree instead of from the raw files.

    A consume run still lists the raw tree, so this makes sure it exists even in a test that only
    ever pointed ``--from-sorted`` at a directory of its own.
    """
    rebuild = not (tmp_path / "raw" / "train").is_dir()
    words = argv(
        tmp_path,
        options=options,
        flags=flags,
        out_name=out_name,
        rebuild=rebuild,
        fmt=fmt,
        typed_statics=typed_statics,
    )
    return words + ["--from-sorted", str(tree)]


def partition_bytes(out: Path) -> dict[str, bytes]:
    """Every written partition, keyed by its path inside the run directory."""
    return {
        path.relative_to(out).as_posix(): path.read_bytes()
        for path in sorted((out / "partitions").rglob("*"))
        if path.is_file()
    }


def workspace_of(tree: Path, path: Path) -> Path:
    """The workspace a raw unit file was sorted into, found the way the CLI finds it."""
    layout = pd.read_csv(tree / "layout.csv")
    row = layout[layout["unit"] == anonymize_unit(unit_from_filename(path))]
    assert len(row) == 1, path.name
    return tree / str(row.iloc[0]["workspace"])


def test_a_sample_run_can_read_the_sorted_tree(tmp_path, capsys):
    tree = sorted_tree(tmp_path)
    code = prep.main(consume_argv(tmp_path, tree))
    assert code == prep.EXIT_OK
    assert list(partition_bytes(tmp_path / "out"))
    assert "sorted tree" in capsys.readouterr().out


def test_a_consume_run_declares_where_its_events_came_from(tmp_path, capsys):
    assert prep.main(argv(tmp_path, options={"--json": ""}, out_name="out_raw")) == prep.EXIT_OK
    assert json.loads(capsys.readouterr().out)["events"] == "raw-files"
    tree = sorted_tree(tmp_path)
    capsys.readouterr()
    code = prep.main(
        consume_argv(tmp_path, tree, options={"--json": ""}, out_name="out_sorted")
    )
    assert code == prep.EXIT_OK
    assert json.loads(capsys.readouterr().out)["events"] == "sorted-tree"


def test_a_sorted_tree_reproduces_the_raw_run_byte_for_byte(tmp_path):
    """The tree is a transport, not a second experiment.

    Same fixture, same bounds, same seed: every partition byte must match, and so must the recorded
    config hash. Anything else means reading the sorted copy changed the data or that the run
    directory is describing an invocation that did not happen.
    """
    assert prep.main(argv(tmp_path, out_name="out_raw")) == prep.EXIT_OK
    tree = sorted_tree(tmp_path)
    assert prep.main(consume_argv(tmp_path, tree, out_name="out_sorted")) == prep.EXIT_OK
    from_raw = partition_bytes(tmp_path / "out_raw")
    assert from_raw, "the raw run wrote no partitions, so there was nothing to compare"
    assert from_raw == partition_bytes(tmp_path / "out_sorted")
    assert read_manifest(tmp_path / "out_raw")["config_hash"] == read_manifest(
        tmp_path / "out_sorted"
    )["config_hash"]


def test_a_feather_run_with_two_static_spellings_reproduces_the_sorted_tree(tmp_path):
    """A stored dtype is not a second opinion about the value.

    The mirror stores ``FrequencyMHz`` as int64 in most units and as float64 with a hole in others,
    so the raw read hands the feature builder a mix of numpy ints and floats, the column infers
    float64, and one value leaves two spellings on disk - the sorted tree carries the same numbers
    as text and infers an integer instead. Measured on 200 real units: 9 612 cells differed and no
    value did. This fixture reproduces that shape without reading the mirror.
    """
    assert prep.main(
        argv(tmp_path, fmt="feather", typed_statics=True, out_name="out_raw")
    ) == prep.EXIT_OK
    tree = sorted_tree(tmp_path, name="sorted_feather", fmt="feather", typed_statics=True)
    assert prep.main(
        consume_argv(
            tmp_path, tree, fmt="feather", typed_statics=True, out_name="out_sorted"
        )
    ) == prep.EXIT_OK
    from_raw = partition_bytes(tmp_path / "out_raw")
    assert from_raw, "the raw run wrote no partitions, so there was nothing to compare"
    assert from_raw == partition_bytes(tmp_path / "out_sorted")
    for name, body in from_raw.items():
        header = body.split(b"\n", 1)[0]
        if b"FrequencyMHz" in header:
            assert b",2666.0," not in body, name
            assert b",32768.0," not in body, name


def test_a_limited_run_reads_only_the_units_it_asked_for(tmp_path):
    # Eight of the fixture's nine units: narrow enough that the tree covers more than the run asks
    # for, wide enough that every split still holds a row and the audit can pass.
    # for, wide enough that every split still holds a row and the audit can pass.
    assert prep.main(
        argv(tmp_path, options={"--max-files": "8"}, out_name="out_raw")
    ) == prep.EXIT_OK
    tree = sorted_tree(tmp_path)
    assert len(pd.read_csv(tree / "layout.csv")) == UNIT_COUNT
    code = prep.main(
        consume_argv(tmp_path, tree, options={"--max-files": "8"}, out_name="out_sorted")
    )
    assert code == prep.EXIT_OK
    assert partition_bytes(tmp_path / "out_raw") == partition_bytes(tmp_path / "out_sorted")


def test_a_tree_that_was_never_sorted_is_refused(tmp_path, capsys):
    empty = tmp_path / "never-sorted"
    empty.mkdir()
    code = prep.main(consume_argv(tmp_path, empty))
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    assert "layout.csv" in err and "--sort-inputs" in err
    assert not (tmp_path / "out" / "partitions").exists()


def test_a_layout_written_by_another_contract_is_refused(tmp_path, capsys):
    tree = sorted_tree(tmp_path)
    frame = pd.read_csv(tree / "layout.csv").drop(columns=["runs"])
    frame.to_csv(tree / "layout.csv", index=False)
    code = prep.main(consume_argv(tmp_path, tree))
    assert code == prep.EXIT_INPUT
    assert "layout.csv" in capsys.readouterr().err


def test_a_unit_with_no_layout_row_is_refused(tmp_path, capsys):
    tree = sorted_tree(tmp_path)
    frame = pd.read_csv(tree / "layout.csv")
    frame.iloc[:-1].to_csv(tree / "layout.csv", index=False)
    code = prep.main(consume_argv(tmp_path, tree))
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    assert "no row in layout.csv" in err
    assert SENTINEL_UNIT not in err


def test_a_layout_that_names_one_unit_twice_is_refused(tmp_path, capsys):
    tree = sorted_tree(tmp_path)
    frame = pd.read_csv(tree / "layout.csv")
    pd.concat([frame, frame.tail(1)], ignore_index=True).to_csv(
        tree / "layout.csv", index=False
    )
    code = prep.main(consume_argv(tmp_path, tree))
    assert code == prep.EXIT_INPUT
    assert "twice" in capsys.readouterr().err


def test_a_raw_file_that_changed_after_the_sort_is_refused(tmp_path, capsys):
    tree = sorted_tree(tmp_path)
    victim = sorted((tmp_path / "raw" / "train").glob("*.csv"))[0]
    with victim.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("appended after the sort\n")
    code = prep.main(consume_argv(tmp_path, tree))
    assert code == prep.EXIT_INPUT
    assert "changed after it was sorted" in capsys.readouterr().err


def test_a_sorted_copy_edited_on_disk_is_refused(tmp_path, capsys):
    tree = sorted_tree(tmp_path)
    victim = sorted((tmp_path / "raw" / "train").glob("*.csv"))[0]
    merged = workspace_of(tree, victim) / MERGED_FILE_NAME
    with merged.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("a row that was never sorted\n")
    code = prep.main(consume_argv(tmp_path, tree))
    assert code == prep.EXIT_INPUT
    assert "digest" in capsys.readouterr().err


def test_a_workspace_missing_its_sidecar_is_refused(tmp_path, capsys):
    """The refusal must be this step's own sentence, not an OS error escaping with a path.

    ``main`` catches ``OSError``, so deleting the check would still exit 1 - with a raw
    ``FileNotFoundError`` whose text happens to name the same file. Only the wording separates the
    two, and only the wording tells an operator what to re-run.
    """
    tree = sorted_tree(tmp_path)
    victim = sorted((tmp_path / "raw" / "train").glob("*.csv"))[0]
    (workspace_of(tree, victim) / SORT_SIDECAR_NAME).unlink()
    code = prep.main(consume_argv(tmp_path, tree))
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    assert "cannot be checked" in err
    assert "FileNotFoundError" not in err


def test_a_workspace_missing_its_sorted_copy_is_refused(tmp_path, capsys):
    tree = sorted_tree(tmp_path)
    victim = sorted((tmp_path / "raw" / "train").glob("*.csv"))[0]
    (workspace_of(tree, victim) / MERGED_FILE_NAME).unlink()
    code = prep.main(consume_argv(tmp_path, tree))
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    assert f"holds no {MERGED_FILE_NAME}" in err
    assert "FileNotFoundError" not in err


def test_a_sidecar_that_records_no_digest_is_refused(tmp_path, capsys):
    """A checkpoint that exists but proves nothing cannot license reading its own output."""
    tree = sorted_tree(tmp_path)
    victim = sorted((tmp_path / "raw" / "train").glob("*.csv"))[0]
    sidecar = workspace_of(tree, victim) / SORT_SIDECAR_NAME
    sidecar.write_text("{}", encoding="utf-8")
    code = prep.main(consume_argv(tmp_path, tree))
    assert code == prep.EXIT_INPUT
    assert "records no input and output digest" in capsys.readouterr().err


def test_a_sidecar_that_is_not_json_is_refused_by_name(tmp_path, capsys):
    tree = sorted_tree(tmp_path)
    victim = sorted((tmp_path / "raw" / "train").glob("*.csv"))[0]
    sidecar = workspace_of(tree, victim) / SORT_SIDECAR_NAME
    sidecar.write_text("sorted, not parsed", encoding="utf-8")
    code = prep.main(consume_argv(tmp_path, tree))
    assert code == prep.EXIT_INPUT
    assert "is not readable JSON" in capsys.readouterr().err


def test_a_dry_run_reads_the_tree_but_still_checks_it(tmp_path, capsys):
    assert prep.main(
        argv(tmp_path, options={"--json": "", "--dry-run": ""})
    ) == prep.EXIT_OK
    from_raw = json.loads(capsys.readouterr().out)
    tree = sorted_tree(tmp_path)
    capsys.readouterr()
    code = prep.main(
        consume_argv(tmp_path, tree, options={"--json": "", "--dry-run": ""})
    )
    assert code == prep.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["events"] == "sorted-tree"
    assert payload["span"] == from_raw["span"]
    assert not (tmp_path / "out" / "partitions").exists()
    victim = sorted((tmp_path / "raw" / "train").glob("*.csv"))[0]
    with victim.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("appended after the sort\n")
    assert (
        prep.main(consume_argv(tmp_path, tree, options={"--dry-run": ""})) == prep.EXIT_INPUT
    )


def test_sorting_and_consuming_in_one_run_is_refused(tmp_path, capsys):
    tree = sorted_tree(tmp_path, name="other")
    code = prep.main(
        argv(
            tmp_path,
            options={"--sort-dir": str(tmp_path / "again")},
            flags=("--sort-inputs", "--from-sorted", str(tree)),
        )
    )
    assert code == prep.EXIT_INPUT
    assert "one mode at a time" in capsys.readouterr().err


def test_profiling_a_sorted_tree_is_refused(tmp_path, capsys):
    tree = sorted_tree(tmp_path)
    code = prep.main(consume_argv(tmp_path, tree, flags=("--profile-only",)))
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    assert "one mode at a time" in err
    assert "profile" in err


def test_a_consume_run_leaves_the_tree_it_read_untouched(tmp_path):
    tree = sorted_tree(tmp_path)
    before = {
        path: path.read_bytes()
        for path in sorted(tree.rglob("*"))
        if path.is_file()
    }
    assert prep.main(consume_argv(tmp_path, tree)) == prep.EXIT_OK
    assert {
        path: path.read_bytes() for path in sorted(tree.rglob("*")) if path.is_file()
    } == before


# ------------------------------------------------- --epoch-unit (the shipped time column)


def _digits(column: pd.Series, divisor: int) -> list[str]:
    """Same instants as bare integers, one per divisor of a nanosecond."""
    stamps = pd.to_datetime(column, format="ISO8601", utc=True)
    return [str(int(value.value) // divisor) for value in stamps]


def epoch_raw(tmp_path: Path, *, name: str = "raw-epoch", divisor: int = 10**9) -> Path:
    """The CSV fixture rewritten so every instant is digits, which is how the package ships them.

    The digits come from the instants the ISO fixture already wrote, so one second means one second
    in both trees and a test may demand the two runs agree byte for byte.
    """
    root = write_fixture(tmp_path / name, fmt="csv")
    for path in sorted((root / "train").glob("*.csv")):
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        frame["log_time"] = _digits(frame["log_time"], divisor)
        frame.to_csv(path, index=False)
    tickets = pd.read_csv(root / "tickets.csv", dtype=str, keep_default_na=False)
    tickets["failure_time"] = _digits(tickets["failure_time"], divisor)
    tickets.to_csv(root / "tickets.csv", index=False)
    return root


def test_digits_without_a_declared_unit_stop_rather_than_guess(tmp_path, capsys):
    raw = epoch_raw(tmp_path)
    code = prep.main(argv(tmp_path, options={"--raw-dir": str(raw)}))
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    assert "epoch_unit" in err
    assert "failure_time" in err


def test_a_dry_run_names_the_event_column_when_the_unit_is_undeclared(tmp_path, capsys):
    raw = epoch_raw(tmp_path)
    code = prep.main(
        argv(tmp_path, options={"--raw-dir": str(raw), "--dry-run": ""}, config=False)
    )
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    assert "epoch_unit" in err
    assert "log_time" in err


def test_an_unknown_epoch_unit_is_reported_as_a_command_mistake(tmp_path, capsys):
    """A flag value outside s/ms must be caught at the parser, not deep inside a time column."""
    code = prep.main(argv(tmp_path, options={"--epoch-unit": "us"}))
    assert code == prep.EXIT_INPUT
    assert "invalid choice" in capsys.readouterr().err


def test_a_declared_epoch_unit_reproduces_the_iso_run_byte_for_byte(tmp_path):
    assert prep.main(argv(tmp_path, out_name="out_iso")) == prep.EXIT_OK
    iso = partition_bytes(tmp_path / "out_iso")
    raw = epoch_raw(tmp_path)
    code = prep.main(
        argv(
            tmp_path,
            options={"--raw-dir": str(raw), "--epoch-unit": "s"},
            out_name="out_epoch",
        )
    )
    assert code == prep.EXIT_OK
    assert partition_bytes(tmp_path / "out_epoch") == iso


def test_a_declared_millisecond_unit_reproduces_the_iso_run_too(tmp_path):
    assert prep.main(argv(tmp_path, out_name="out_iso")) == prep.EXIT_OK
    iso = partition_bytes(tmp_path / "out_iso")
    raw = epoch_raw(tmp_path, name="raw-epoch-ms", divisor=10**6)
    code = prep.main(
        argv(
            tmp_path,
            options={"--raw-dir": str(raw), "--epoch-unit": "ms"},
            out_name="out_ms",
        )
    )
    assert code == prep.EXIT_OK
    assert partition_bytes(tmp_path / "out_ms") == iso


def test_millisecond_digits_read_as_seconds_are_caught_not_swallowed(tmp_path, capsys):
    """The flag is doing arithmetic, not merely silencing a refusal.

    Millisecond digits read as seconds land years past the bounds, so the run must stop with an
    out-of-range complaint instead of writing an empty sample set.
    """
    raw = epoch_raw(tmp_path, name="raw-epoch-ms", divisor=10**6)
    code = prep.main(
        argv(
            tmp_path,
            options={"--raw-dir": str(raw), "--epoch-unit": "s"},
            out_name="out_wrong",
        )
    )
    assert code == prep.EXIT_INPUT
    assert "out of range" in capsys.readouterr().err


def test_a_redundant_epoch_unit_declaration_moves_no_row(tmp_path):
    assert prep.main(argv(tmp_path, out_name="out_plain")) == prep.EXIT_OK
    plain = partition_bytes(tmp_path / "out_plain")
    code = prep.main(argv(tmp_path, options={"--epoch-unit": "s"}, out_name="out_inert"))
    assert code == prep.EXIT_OK
    assert partition_bytes(tmp_path / "out_inert") == plain


def test_a_declared_epoch_unit_is_part_of_the_configs_identity(tmp_path, capsys):
    assert prep.main(argv(tmp_path)) == prep.EXIT_OK
    capsys.readouterr()
    code = prep.main(argv(tmp_path, options={"--epoch-unit": "s"}, flags=("--resume",)))
    assert code == prep.EXIT_CONFIG
    assert "config differs" in capsys.readouterr().err


def test_profiling_digits_needs_the_same_declared_unit(tmp_path, capsys):
    raw = epoch_raw(tmp_path, name="raw-epoch-profile")
    code = prep.main(argv(tmp_path, options={"--raw-dir": str(raw), "--profile-only": ""}))
    assert code == prep.EXIT_INPUT
    assert "epoch_unit" in capsys.readouterr().err
    code = prep.main(
        argv(
            tmp_path,
            options={
                "--raw-dir": str(raw),
                "--profile-only": "",
                "--epoch-unit": "s",
                "--error-types": "ce,ue",
            },
            out_name="out_profile",
        )
    )
    assert code == prep.EXIT_OK
    assert partition_bytes(tmp_path / "out_profile")


def test_sorting_digits_needs_the_same_declared_unit(tmp_path, capsys):
    raw = epoch_raw(tmp_path, name="raw-epoch-sort")
    blocked = sort_argv(
        tmp_path,
        options={"--raw-dir": str(raw), "--sort-dir": str(tmp_path / "sorted_blocked")},
    )
    assert prep.main(blocked) == prep.EXIT_INPUT
    assert "epoch_unit" in capsys.readouterr().err
    code = prep.main(
        sort_argv(
            tmp_path,
            options={"--raw-dir": str(raw), "--epoch-unit": "s",
                     "--sort-dir": str(tmp_path / "sorted_epoch")},
        )
    )
    assert code == prep.EXIT_OK


# ------------------------------------------- --error-types (the declared value domain)

#: The two spellings the two trees use. The fixture writes lowercase abbreviations, while a
#: 460-file sample of the shipped package measured on 2026-10-03 (6 245 208 rows of a 62 224-file
#: mirror) holds dotted uppercase names.
FIXTURE_TYPES = ("ce", "ue")
LOG_TYPES = {"ce": "CE.READ", "ue": "CE.SCRUB"}


def typed_raw(tmp_path: Path, rename: dict[str, str], *, name: str = "raw-typed") -> Path:
    """The CSV fixture with every error_type value renamed, which is all the real logs differ by.

    An unknown value raises instead of passing through, so a test cannot silently profile a tree
    whose rows it did not rewrite.
    """
    root = write_fixture(tmp_path / name, fmt="csv")
    for path in sorted((root / "train").glob("*.csv")):
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        frame["error_type"] = frame["error_type"].map(lambda value: rename[value])
        frame.to_csv(path, index=False)
    return root


def reader_types(root: Path) -> dict[str, int]:
    """The values the reader keeps per name, summed here instead of inside the profile.

    Counting it a second way is the point: the profile has to agree with a run that adds up one
    file at a time, including the files that contribute nothing.
    """
    counts: dict[str, int] = {}
    for path in sorted((root / "train").glob("*.csv")):
        frame = read_smartmem_file(path, fmt="csv", timezone="UTC")
        for value, rows in frame["error_type"].value_counts().items():
            counts[str(value)] = counts.get(str(value), 0) + int(rows)
    return counts


#: A domain wider than a refusal prints, so the tail of it has to be counted rather than listed.
MANY_TYPES = tuple(f"TYPE.{index}" for index in range(1, 8))


def many_type_raw(tmp_path: Path, *, name: str = "raw-many") -> Path:
    """One error type per unit file, which makes the observed domain seven names wide."""
    root = write_fixture(tmp_path / name, fmt="csv")
    for index, path in enumerate(sorted((root / "train").glob("*.csv"))):
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        frame["error_type"] = MANY_TYPES[index % len(MANY_TYPES)]
        frame.to_csv(path, index=False)
    return root


def header_only_raw(tmp_path: Path, *, name: str = "raw-header-only") -> Path:
    """The fixture with every event row dropped: a tree that can cover no declared name."""
    root = write_fixture(tmp_path / name, fmt="csv")
    for path in sorted((root / "train").glob("*.csv")):
        header = path.read_text(encoding="utf-8").splitlines()[0]
        path.write_text(f"{header}\n", encoding="utf-8")
    return root


def profile_rows(out: Path) -> pd.DataFrame:
    """The tidy schema table the profile partition holds."""
    return pd.read_csv(out / "partitions" / "profile")


def error_type_rows(out: Path) -> dict[str, int]:
    """Declared or observed error types with the rows each one holds, read back from the profile."""
    seen = profile_rows(out)
    seen = seen[seen["scope"] == "error_type"]
    return {str(row.name): int(row.value) for row in seen.itertuples()}


def test_a_default_domain_that_matches_nothing_stops_the_run(tmp_path, capsys):
    """The shipped default now describes the real logs, so a lowercase tree has to say so itself.

    This is the trap the check exists for: a domain that matches no row still writes a table, and
    every error type feature in it reads as unexpected without any of the columns complaining.
    """
    code = prep.main(argv(tmp_path, options={"--profile-only": ""}))
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    assert "--error-types" in err
    for name in FIXTURE_TYPES:
        assert repr(name) in err
    assert repr("CE.READ") in err


def test_a_default_domain_that_matches_nothing_writes_no_partition(tmp_path):
    assert (
        prep.main(argv(tmp_path, options={"--profile-only": ""}, out_name="out_refused"))
        == prep.EXIT_INPUT
    )
    assert not list((tmp_path / "out_refused" / "partitions").rglob("*"))


def test_the_default_domain_covers_the_values_the_logs_hold(tmp_path):
    raw = typed_raw(tmp_path, LOG_TYPES)
    code = prep.main(
        argv(
            tmp_path,
            options={"--raw-dir": str(raw), "--profile-only": ""},
            out_name="out_log",
        )
    )
    assert code == prep.EXIT_OK
    observed = reader_types(raw)
    assert set(observed) == {"CE.READ", "CE.SCRUB"}
    # the third declared name is one the logs never show, and the table has to say so plainly
    assert error_type_rows(tmp_path / "out_log") == {**observed, "CE": 0}


def test_a_declared_domain_is_compared_exactly_as_spelled(tmp_path, capsys):
    """Case is part of the value, so a lowercase declaration against uppercase rows is refused."""
    raw = typed_raw(tmp_path, LOG_TYPES, name="raw-typed-case")
    code = prep.main(
        argv(
            tmp_path,
            options={"--raw-dir": str(raw), "--profile-only": "", "--error-types": "ce,ue"},
        )
    )
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    assert repr("CE.READ") in err
    assert "as spelled" in err


def test_a_declared_type_the_logs_never_show_is_recorded_as_zero_rows(tmp_path):
    """Only a domain that covers nothing is a mistake; a type with no rows is a fact to print."""
    raw = typed_raw(tmp_path, LOG_TYPES, name="raw-typed-partial")
    code = prep.main(
        argv(
            tmp_path,
            options={
                "--raw-dir": str(raw),
                "--profile-only": "",
                "--error-types": "CE.READ,CE",
            },
            out_name="out_partial",
        )
    )
    assert code == prep.EXIT_OK
    assert error_type_rows(tmp_path / "out_partial") == {**reader_types(raw), "CE": 0}


def test_an_empty_error_type_domain_is_refused_before_anything_runs(tmp_path, capsys):
    # the value is ", ," rather than "" because an empty flag argument would be argparse's problem
    code = prep.main(argv(tmp_path, options={"--error-types": ", ,", "--profile-only": ""}))
    assert code == prep.EXIT_INPUT
    assert "empty" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_two_error_types_that_name_one_column_are_refused(tmp_path, capsys):
    """``CE.READ`` and ``CE_READ`` both slug to ``ce_read_count``, so one count would be lost."""
    code = prep.main(
        argv(tmp_path, options={"--error-types": "CE.READ,CE_READ", "--profile-only": ""})
    )
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    assert "ce_read_count" in err
    assert not (tmp_path / "out").exists()


def test_a_repeated_error_type_declaration_is_refused(tmp_path, capsys):
    code = prep.main(argv(tmp_path, options={"--error-types": "ce,ce", "--profile-only": ""}))
    assert code == prep.EXIT_INPUT
    assert "ce_count" in capsys.readouterr().err


def test_padding_in_a_declaration_is_not_part_of_the_name(tmp_path):
    """``ce, ue`` and ``ce,ue`` are one domain: a space between names is not in any of them."""
    tight = {"--profile-only": "", "--error-types": "ce,ue"}
    assert prep.main(argv(tmp_path, options=tight, out_name="out_tight")) == prep.EXIT_OK
    bytes_of_tight = partition_bytes(tmp_path / "out_tight")
    padded = {"--profile-only": "", "--error-types": "ce, ue"}
    assert prep.main(argv(tmp_path, options=padded, out_name="out_padded")) == prep.EXIT_OK
    assert partition_bytes(tmp_path / "out_padded") == bytes_of_tight


def test_a_refusal_names_five_types_and_counts_the_rest(tmp_path, capsys):
    """The message points at the mismatch instead of inventorying a domain wider than a screen."""
    raw = many_type_raw(tmp_path)
    code = prep.main(argv(tmp_path, options={"--raw-dir": str(raw), "--profile-only": ""}))
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    for name in MANY_TYPES[:5]:
        assert repr(name) in err
    assert repr(MANY_TYPES[-1]) not in err
    assert f"plus {len(MANY_TYPES) - 5} more" in err


def test_a_tree_that_holds_no_event_row_says_so(tmp_path, capsys):
    """An empty tree is not a domain mismatch to print names for; there is nothing to name."""
    raw = header_only_raw(tmp_path)
    code = prep.main(argv(tmp_path, options={"--raw-dir": str(raw), "--profile-only": ""}))
    assert code == prep.EXIT_INPUT
    err = capsys.readouterr().err
    assert "no error_type value at all" in err
    assert not list((tmp_path / "out" / "partitions").rglob("*"))


def test_the_sample_mode_declares_its_domain_the_same_way(tmp_path):
    """The parse-time checks run for every mode, not only for the one that prints a profile."""
    assert prep.main(argv(tmp_path, options={"--error-types": ","})) == prep.EXIT_INPUT
    assert not (tmp_path / "out").exists()

    raw = typed_raw(tmp_path, LOG_TYPES, name="raw-typed-sample")
    code = prep.main(
        argv(
            tmp_path,
            options={"--raw-dir": str(raw), "--error-types": "CE.READ,CE.SCRUB"},
            out_name="out_typed",
        )
    )
    assert code == prep.EXIT_OK
    written = sorted(
        path for path in (tmp_path / "out_typed" / "partitions" / "samples").rglob("*")
        if path.is_file()
    )
    assert written
    columns = set(pd.read_csv(written[0], nrows=0).columns)
    declared = {"ce_read_count", "ce_scrub_count", "unexpected_error_type_count"}
    assert declared <= columns


# ---------------------------------------------------------------- unit -> type side table


def read_unit_types(out: Path) -> pd.DataFrame:
    return pd.read_csv(out / "partitions" / prep.UNIT_TYPE_PARTITION)


def relocate(raw: Path, unit: str, queue: str) -> None:
    """Move one fixture unit into a queue directory, which is a declared source of its type."""
    target = raw / queue
    target.mkdir(parents=True, exist_ok=True)
    shutil.move(str(raw / "train" / f"{unit}.csv"), str(target / f"{unit}.csv"))


def test_the_run_writes_a_side_table_with_one_type_per_unit(tmp_path, capsys):
    code = prep.main(argv(tmp_path, options={"--json": ""}))
    assert code == prep.EXIT_OK
    table = read_unit_types(tmp_path / "out")
    assert list(table.columns) == list(UNIT_TYPE_COLUMNS)
    # unit_id repeats the name the sample table writes, so the two join with no second hashing step
    assert sorted(table["unit_id"]) == sorted(EVENTS_BY_UNIT)
    by_unit = table.set_index("unit_id")
    for unit in sorted(FAILURE_TIME_BY_UNIT):
        assert by_unit.loc[unit, "source"] == "ticket"
        assert by_unit.loc[unit, "serial_number_type"] == SERIAL_TYPE_BY_UNIT[unit]
    quiet = table[table["source"] == prep.UNIT_TYPE_UNRESOLVED]
    assert sorted(quiet["unit_id"]) == sorted(set(EVENTS_BY_UNIT) - set(FAILURE_TIME_BY_UNIT))
    assert quiet["serial_number_type"].isna().all()
    payload = json.loads(capsys.readouterr().out)
    assert payload["unit_types"] == {
        "rows": UNIT_COUNT,
        "declared": len(FAILURE_TIME_BY_UNIT),
        "unresolved": UNIT_COUNT - len(FAILURE_TIME_BY_UNIT),
    }


def test_a_queue_directory_declares_a_type_for_a_unit_no_ticket_covers(tmp_path):
    raw = raw_dir(tmp_path)
    # unit-clean has no ticket, so its type comes from nowhere before the move and from the
    # directory after it - which is the case a ticket-only table would silently leave blank
    relocate(raw, "unit-clean", "type_B")
    code = prep.main(argv(tmp_path, options={"--raw-dir": str(raw)}, rebuild=False))
    assert code == prep.EXIT_OK
    row = read_unit_types(tmp_path / "out").set_index("unit_id").loc["unit-clean"]
    assert row["source"] == "queue_directory"
    assert row["serial_number_type"] == "B"


def test_a_directory_and_a_ticket_that_disagree_stop_the_run(tmp_path, capsys):
    raw = raw_dir(tmp_path)
    relocate(raw, "unit-lead-hit", "type_B")  # and its ticket declares A
    code = prep.main(argv(tmp_path, options={"--raw-dir": str(raw)}, rebuild=False))
    assert code == prep.EXIT_INPUT
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "queue directory" in combined and "ticket" in combined
    assert anonymize_unit("unit-lead-hit") in combined
    assert "unit-lead-hit" not in combined
    assert not (tmp_path / "out").exists()


def test_the_side_table_covers_every_unit_the_sample_table_names(tmp_path):
    """These two join on the unit when somebody writes a submission, so a missing row is a unit
    nobody can type - and the join key is the same raw name in both, not a second hash of it."""
    assert prep.main(argv(tmp_path)) == prep.EXIT_OK
    out = tmp_path / "out"
    written = sorted(path for path in (out / "partitions" / prep.SAMPLES_DIR).rglob("*"))
    frames = [pd.read_csv(path, dtype={"unit_id": str}) for path in written if path.is_file()]
    assert frames, "the run wrote no sample partition, so there was nothing to join against"
    named = {value for frame in frames for value in frame["unit_id"]}
    assert named <= set(read_unit_types(out)["unit_id"])
    assert prep.UNIT_TYPE_PARTITION in read_manifest(out)["partitions"]


def test_the_side_table_survives_the_sorted_tree_without_losing_its_queue(tmp_path):
    raw = raw_dir(tmp_path)
    relocate(raw, "unit-clean", "type_A")
    assert prep.main(argv(tmp_path, out_name="out_raw", rebuild=False)) == prep.EXIT_OK
    tree = sorted_tree(tmp_path, name="sorted_queues", rebuild=False)
    assert prep.main(consume_argv(tmp_path, tree, out_name="out_sorted")) == prep.EXIT_OK
    body = (tmp_path / "out_raw" / "partitions" / prep.UNIT_TYPE_PARTITION).read_bytes()
    assert (tmp_path / "out_sorted" / "partitions" / prep.UNIT_TYPE_PARTITION).read_bytes() == body

    row = read_unit_types(tmp_path / "out_sorted").set_index("unit_id").loc["unit-clean"]
    assert row["source"] == "queue_directory"


def test_a_ticket_type_edit_is_caught_by_the_side_table_fingerprint(tmp_path):
    raw = raw_dir(tmp_path)
    assert prep.main(argv(tmp_path)) == prep.EXIT_OK
    tickets = raw / "tickets.csv"
    frame = pd.read_csv(tickets)
    # one ticket for this unit, so the edit changes what the queue declares without making the
    # tickets contradict each other, which is a different check with a different message
    rows = frame.index[frame["serial_number"] == "unit-lead-hit"].tolist()
    assert len(rows) == 1
    frame.loc[rows, "serial_number_type"] = (
        "B" if frame.loc[rows[0], "serial_number_type"] == "A" else "A"
    )
    frame.to_csv(tickets, index=False)
    # the event files are untouched, so the listing fingerprint cannot see this edit; the side
    # table can, and a run that would pair new samples with the old declared types is refused
    assert prep.main(argv(tmp_path, flags=("--resume",), rebuild=False)) == prep.EXIT_CONFIG
    # a fresh run directory takes it, so this is the resume guard speaking and not a broken input
    assert prep.main(argv(tmp_path, out_name="out_fresh", rebuild=False)) == prep.EXIT_OK
