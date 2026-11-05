"""The local SN-level scorer: what a provisional metric spec has to prove before it prints a number.

Every score pinned here is hand-computed from the fixture timeline in ``helpers_smartmem.py``, whose
anchors and failure instants are listed in that file's docstring. Three things are non-negotiable in
this file and each gets its own test: a submission must pay for the alarms it ignored, a rule that
changes a number has to stay a flag rather than a constant, and a slice with nothing to score is
reported as unscorable instead of as a zero.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.smartmem import evaluator as ev  # noqa: E402
from benchmark.smartmem import prepare_data as prep  # noqa: E402
from faultevolve.data.manifest import read_manifest  # noqa: E402
from helpers_smartmem import SENTINEL_UNIT, write_fixture  # noqa: E402

BOUNDS = {
    "start": "2024-01-01",
    "train_until": "2024-03-01",
    "dev_until": "2024-03-20",
    "val_until": "2024-04-08",
    "outcome_observed_until": "2024-04-30",
}
TWO_HOURS = pd.Timedelta(hours=2)


@pytest.fixture(scope="module")
def workspace(tmp_path_factory) -> Path:
    """One prepared run directory for the module: 23 sample rows, four splits, no real data."""
    root = tmp_path_factory.mktemp("evaluator")
    raw = write_fixture(root / "raw")
    config = root / "split.yaml"
    config.write_text(yaml.safe_dump(BOUNDS, sort_keys=False), encoding="utf-8")
    assert prep.main(
        [
            "--raw-dir", str(raw), "--out-dir", str(root / "out"), "--format", "csv",
            "--timezone", "UTC", "--split-config", str(config),
        ]
    ) == prep.EXIT_OK
    return root


def samples(out: Path) -> pd.DataFrame:
    """The sample table as written, so a test can name rows by unit and instant."""
    files = sorted(p for p in (out / "partitions" / "samples").rglob("*") if p.is_file())
    frame = pd.concat([pd.read_csv(p) for p in files], ignore_index=True)
    for column in ("prediction_time", "history_end"):
        frame[column] = pd.to_datetime(frame[column], format="ISO8601", utc=True)
    return frame


def write_predictions(path: Path, rows: pd.DataFrame) -> Path:
    """Submit exactly these sample rows, each predicted at the instant its own row was built for."""
    rows.loc[:, ["sample_id", "prediction_time"]].to_csv(path, index=False)
    return path


def ticket_file(path: Path, alarms: list[tuple[str, str, str]]) -> Path:
    frame = pd.DataFrame(alarms, columns=["serial_number", "failure_time", "serial_number_type"])
    frame.to_csv(path, index=False)
    return path


def type_table(path: Path, declared: dict[str, str]) -> Path:
    pd.DataFrame(
        [(unit, kind) for unit, kind in declared.items()],
        columns=["unit_id", "serial_number_type"],
    ).to_csv(path, index=False)
    return path


def score(workspace: Path, capsys, *, split: str, predictions: Path, **flags: str) -> dict:
    """Run one scoring pass in ``--json`` mode and hand back the object it printed."""
    words = [
        "--run-dir", str(workspace / "out"),
        "--ticket-file", str(flags.pop("ticket", workspace / "raw" / "tickets.csv")),
        "--predictions", str(predictions),
        "--split", split,
        "--json",
    ]
    words += [item for name, value in flags.items() for item in (name, value)]
    code = ev.main(words)
    printed = capsys.readouterr().out.strip()
    return {"exit_code": code, "payload": json.loads(printed) if printed else None}


# ------------------------------------------------------------ the recorded rule and its brackets


def test_three_instants_on_one_unit_are_free_under_the_recorded_rule_and_cost_forty_under_one(
    workspace, tmp_path, capsys
):
    """train holds three anchors of unit-dup-events inside one alarm window. The wording the
    official pages record counts a serial number once, whichever of its predictions hit, so all
    three instants are one true positive and F stays 1.0. The tight local fallback pairs one alarm
    with one prediction and charges the other two as false positives, dropping F to 0.5."""
    held = samples(workspace / "out")
    rows = held.loc[held["unit_id"] == "unit-dup-events"]
    assert len(rows) == 3
    predictions = write_predictions(tmp_path / "p.csv", rows)

    recorded = score(workspace, capsys, split="train", predictions=predictions)
    assert recorded["exit_code"] == ev.EXIT_OK
    assert recorded["payload"]["duplicate_alarm_rule"] == "sn-in-window"
    assert recorded["payload"]["totals"] == {
        "tp": 1, "fp": 0, "fn": 0, "alarms": 1, "predictions": 1,
        "precision": 1.0, "recall": 1.0, "f_beta": 1.0,
    }
    tight = score(
        workspace, capsys, split="train", predictions=predictions,
        **{"--duplicate-alarm-rule": "each-alarm"},
    )
    assert tight["payload"]["totals"] == {
        "tp": 1, "fp": 2, "fn": 0, "alarms": 1, "predictions": 3,
        "precision": 0.333333, "recall": 1.0, "f_beta": 0.5,
    }
    assert recorded["payload"]["metric_spec_status"] == "provisional"


def test_a_unit_named_at_an_instant_no_window_covers_is_not_a_hit(workspace, tmp_path, capsys):
    """The boundary between the recorded rule and the coarse one. unit-static-late alarmed at
    2024-01-18 08:00, whose window [01-11 08:00, 01-18 07:45] its 01-01 anchor misses, so a scorer
    that only asks whether the model named the unit calls this a perfect run while the recorded
    wording calls it one false positive and one missed alarm."""
    held = samples(workspace / "out")
    alarms = ticket_file(
        tmp_path / "t.csv", [("unit-static-late", "2024-01-18T08:00:00+00:00", "A")]
    )
    one = held.loc[held["prediction_time"] == pd.Timestamp("2024-01-01 00:00:00+00:00")]
    assert len(one) == 1
    predictions = write_predictions(tmp_path / "p.csv", one)

    recorded = score(workspace, capsys, split="train", predictions=predictions, ticket=alarms)
    assert recorded["payload"]["totals"] == {
        "tp": 0, "fp": 1, "fn": 1, "alarms": 1, "predictions": 1,
        "precision": 0.0, "recall": 0.0, "f_beta": 0.0,
    }
    coarse = score(
        workspace, capsys, split="train", predictions=predictions, ticket=alarms,
        **{"--duplicate-alarm-rule": "once-per-unit"},
    )
    assert coarse["payload"]["totals"] == {
        "tp": 1, "fp": 0, "fn": 0, "alarms": 1, "predictions": 1,
        "precision": 1.0, "recall": 1.0, "f_beta": 1.0,
    }


def test_the_default_rule_says_where_its_wording_came_from(workspace, tmp_path, capsys):
    """A reader who sees one number has to be able to ask which of three incompatible readings made
    it, and on whose authority, without opening the source."""
    held = samples(workspace / "out")
    predictions = write_predictions(
        tmp_path / "p.csv", held.loc[held["unit_id"] == "unit-dup-events"]
    )
    recorded = score(workspace, capsys, split="train", predictions=predictions)
    assert "official" in recorded["payload"]["rule_provenance"]
    tight = score(
        workspace, capsys, split="train", predictions=predictions,
        **{"--duplicate-alarm-rule": "each-alarm"},
    )
    assert "REQUIREMENTS" in tight["payload"]["rule_provenance"]
    assert tight["payload"]["rule_provenance"] != recorded["payload"]["rule_provenance"]


def test_two_alarms_on_one_unit_are_two_events_under_one_rule_and_one_under_the_other(
    workspace, tmp_path, capsys
):
    """The same unit alarmed at 2024-02-19 22:00 and 2024-02-25 00:00, so its hit windows are
    [02-12 22:00, 02-19 21:45] and [02-18 00:00, 02-24 23:45]. A prediction at 02-20 12:00 can only
    reach the second one: the tight local fallback owes a missed alarm for the first, while the
    recorded rule counts the serial number once and stops asking."""
    alarms = ticket_file(
        tmp_path / "t.csv",
        [
            ("unit-dup-events", "2024-02-25T00:00:00+00:00", "B"),
            ("unit-dup-events", "2024-02-19T22:00:00+00:00", "B"),
        ],
    )
    rows = samples(workspace / "out")
    one = rows.loc[rows["prediction_time"] == pd.Timestamp("2024-02-20 12:00:00+00:00")]
    predictions = write_predictions(tmp_path / "p.csv", one)

    tight = score(
        workspace, capsys, split="train", predictions=predictions, ticket=alarms,
        **{"--duplicate-alarm-rule": "each-alarm"},
    )
    assert tight["payload"]["totals"] == {
        "tp": 1, "fp": 0, "fn": 1, "alarms": 2, "predictions": 1,
        "precision": 1.0, "recall": 0.5, "f_beta": 0.666667,
    }
    recorded = score(workspace, capsys, split="train", predictions=predictions, ticket=alarms)
    assert recorded["payload"]["totals"] == {
        "tp": 1, "fp": 0, "fn": 0, "alarms": 1, "predictions": 1,
        "precision": 1.0, "recall": 1.0, "f_beta": 1.0,
    }


def test_covering_both_windows_is_the_only_way_to_reach_one_under_the_tight_rule(
    workspace, tmp_path, capsys
):
    held = samples(workspace / "out")
    alarms = ticket_file(
        tmp_path / "t.csv",
        [
            ("unit-dup-events", "2024-02-25T00:00:00+00:00", "B"),
            ("unit-dup-events", "2024-02-19T22:00:00+00:00", "B"),
        ],
    )
    both = held.loc[
        held["prediction_time"].isin(
            [pd.Timestamp("2024-02-19 20:00:00+00:00"), pd.Timestamp("2024-02-20 12:00:00+00:00")]
        )
    ]
    predictions = write_predictions(tmp_path / "p.csv", both)
    result = score(
        workspace, capsys, split="train", predictions=predictions, ticket=alarms,
        **{"--duplicate-alarm-rule": "each-alarm"},
    )
    assert result["payload"]["totals"] == {
        "tp": 2, "fp": 0, "fn": 0, "alarms": 2, "predictions": 2,
        "precision": 1.0, "recall": 1.0, "f_beta": 1.0,
    }


# ---------------------------------------------------------------- who owns the denominator


def test_a_submission_that_ignores_the_failing_unit_scores_zero_not_a_perfect_recall(
    workspace, tmp_path, capsys
):
    """Four rows of a unit that never alarmed, and the one unit that did is left alone. The alarms
    this slice must cover are fixed by the run directory, not by what the model chose to mention, so
    the ignored alarm is a false negative and recall cannot be 1.0 - and the queue nobody predicted
    still has to appear in the report."""
    held = samples(workspace / "out")
    quiet = held.loc[
        (held["unit_id"] == "unit-static-late") & (held["split_key"] == "train")
    ]
    predictions = write_predictions(tmp_path / "p.csv", quiet)
    result = score(workspace, capsys, split="train", predictions=predictions)
    payload = result["payload"]
    assert result["exit_code"] == ev.EXIT_OK
    assert payload["scoreable"] is True
    assert payload["totals"] == {
        "tp": 0, "fp": 1, "fn": 1, "alarms": 1, "predictions": 1,
        "precision": 0.0, "recall": 0.0, "f_beta": 0.0,
    }
    assert set(payload["queues"]) == {"B", "unknown"}
    assert payload["queues"]["B"] == {
        "tp": 0, "fp": 0, "fn": 1, "alarms": 1, "predictions": 0,
        "precision": None, "recall": 0.0, "f_beta": 0.0,
    }
    assert payload["unknown_type_units"] == 5
    assert payload["rows_scored"] == 8
    tight = score(
        workspace, capsys, split="train", predictions=predictions,
        **{"--duplicate-alarm-rule": "each-alarm"},
    )
    assert tight["payload"]["queues"]["B"] == {
        "tp": 0, "fp": 0, "fn": 1, "alarms": 1, "predictions": 0,
        "precision": None, "recall": 0.0, "f_beta": 0.0,
    }
    # Four rows of one silent unit are four predictions to the tight rule and one serial number to
    # the recorded one; both still owe the alarm nobody mentioned.
    assert tight["payload"]["totals"] == {
        "tp": 0, "fp": 4, "fn": 1, "alarms": 1, "predictions": 4,
        "precision": 0.0, "recall": 0.0, "f_beta": 0.0,
    }


def test_the_two_queues_do_not_have_to_be_averaged_and_the_two_answers_differ(
    workspace, tmp_path, capsys
):
    """unit-static-late is declared queue A by a table nobody else holds, and alarmed at
    2024-01-18 08:00, whose window [01-11 08:00, 01-18 07:45] covers one of its four train anchors.
    Queue B scores 0.5, queue A scores 0.0: summing counts gives F = 2*0.25*0.5/0.75 = 1/3, while
    averaging the two F values gives 0.25. A skew this small already separates the two readings,
    which is why the flag is provisional and not a constant.

    The counting rule is pinned to ``each-alarm`` here on purpose: how the queues combine is a
    separate question from how a unit's instants combine, and this fixture is skewed enough to
    separate the two answers only under the tight rule."""
    held = samples(workspace / "out")
    alarms = ticket_file(
        tmp_path / "t.csv",
        [
            ("unit-dup-events", "2024-02-25T00:00:00+00:00", "B"),
            ("unit-static-late", "2024-01-18T08:00:00+00:00", "A"),
        ],
    )
    declared = type_table(
        tmp_path / "types.csv", {"unit-dup-events": "B", "unit-static-late": "A"}
    )
    picked = held.loc[
        (held["unit_id"] == "unit-dup-events")
        | (held["prediction_time"] == pd.Timestamp("2024-01-01 00:00:00+00:00"))
    ]
    assert len(picked) == 4
    predictions = write_predictions(tmp_path / "p.csv", picked)

    summed = score(
        workspace, capsys, split="train", predictions=predictions, ticket=alarms,
        **{
            "--unit-type-table": str(declared),
            "--duplicate-alarm-rule": "each-alarm",
        },
    )
    assert summed["payload"]["queues"]["B"]["f_beta"] == 0.5
    assert summed["payload"]["queues"]["A"] == {
        "tp": 0, "fp": 1, "fn": 1, "alarms": 1, "predictions": 1,
        "precision": 0.0, "recall": 0.0, "f_beta": 0.0,
    }
    assert summed["payload"]["f_beta"] == pytest.approx(1 / 3, abs=1e-6)
    averaged = score(
        workspace, capsys, split="train", predictions=predictions, ticket=alarms,
        **{
            "--unit-type-table": str(declared),
            "--duplicate-alarm-rule": "each-alarm",
            "--queue-aggregation": "mean-of-f1",
        },
    )
    assert averaged["payload"]["f_beta"] == 0.25


# ---------------------------------------------------------------- what stops a run


def test_a_slice_with_no_alarm_in_any_window_is_not_scorable_rather_than_zero(
    workspace, tmp_path, capsys
):
    """val's four anchors sit just outside both of its units' hit windows, so nothing here could
    have been predicted correctly at all. A 0.0 would read as a failed model; this exits 4 and says
    so."""
    held = samples(workspace / "out")
    predictions = write_predictions(tmp_path / "p.csv", held.loc[held["split_key"] == "val"])
    result = score(workspace, capsys, split="val", predictions=predictions)
    assert result["exit_code"] == ev.EXIT_NOT_SCORABLE
    assert result["payload"]["scoreable"] is False
    assert "f_beta" not in json.dumps(result["payload"])
    assert result["payload"]["rows_scored"] == 4


def test_a_prediction_issued_two_hours_early_is_refused(workspace, tmp_path, capsys):
    held = samples(workspace / "out")
    row = held.loc[held["unit_id"] == "unit-dup-events"].iloc[0]
    early = pd.DataFrame(
        [{"sample_id": row["sample_id"], "prediction_time": row["history_end"] - TWO_HOURS}]
    )
    early.to_csv(tmp_path / "p.csv", index=False)
    code = ev.main(
        [
            "--run-dir", str(workspace / "out"),
            "--ticket-file", str(workspace / "raw" / "tickets.csv"),
            "--predictions", str(tmp_path / "p.csv"), "--split", "train",
        ]
    )
    assert code == ev.EXIT_INPUT
    assert "before the last event" in capsys.readouterr().err


def test_a_prediction_naming_a_sample_that_does_not_exist_is_refused(workspace, tmp_path, capsys):
    pd.DataFrame(
        [{"sample_id": "evs-v1-" + "0" * 32, "prediction_time": "2024-02-19T20:00:00+00:00"}]
    ).to_csv(tmp_path / "p.csv", index=False)
    code = ev.main(
        [
            "--run-dir", str(workspace / "out"),
            "--ticket-file", str(workspace / "raw" / "tickets.csv"),
            "--predictions", str(tmp_path / "p.csv"), "--split", "train",
        ]
    )
    assert code == ev.EXIT_INPUT
    assert "does not hold" in capsys.readouterr().err


def test_predictions_from_another_slice_are_refused_rather_than_scored(workspace, tmp_path, capsys):
    """Scoring one slice per call is a rule, not a courtesy: a dev prediction would be credited
    against train's alarms and the number would mean neither."""
    held = samples(workspace / "out")
    dev = held.loc[held["split_key"] == "dev"]
    predictions = write_predictions(tmp_path / "p.csv", dev)
    code = ev.main(
        [
            "--run-dir", str(workspace / "out"),
            "--ticket-file", str(workspace / "raw" / "tickets.csv"),
            "--predictions", str(tmp_path / "p.csv"), "--split", "train",
        ]
    )
    assert code == ev.EXIT_INPUT
    assert "outside the 'train' slice" in capsys.readouterr().err


def test_a_config_hash_mismatch_is_refused_before_any_number_is_printed(
    workspace, tmp_path, capsys
):
    held = samples(workspace / "out")
    predictions = write_predictions(
        tmp_path / "p.csv", held.loc[held["unit_id"] == "unit-dup-events"]
    )
    recorded = read_manifest(workspace / "out")["config_hash"]
    assert (
        score(
            workspace, capsys, split="train", predictions=predictions,
            **{"--expect-config-hash": recorded},
        )["exit_code"]
        == ev.EXIT_OK
    )
    assert (
        score(
            workspace, capsys, split="train", predictions=predictions,
            **{"--expect-config-hash": "f" * 64},
        )["exit_code"]
        == ev.EXIT_INPUT
    )


# ---------------------------------------------------------------- what a payload may contain


def test_no_serial_number_and_no_row_of_any_unit_reaches_the_output(
    workspace, tmp_path, capsys
):
    """The sentinel unit's name is a stand-in for a real serial, and it does hold train rows. Only
    counts and anonymised sample ids may leave this file."""
    held = samples(workspace / "out")
    everything = held.loc[held["split_key"] == "train"]
    predictions = write_predictions(tmp_path / "p.csv", everything)
    result = score(workspace, capsys, split="train", predictions=predictions)
    printed = json.dumps(result["payload"])
    assert SENTINEL_UNIT not in printed
    assert "unit-" not in printed
    assert result["payload"]["units_scored"] == 3
