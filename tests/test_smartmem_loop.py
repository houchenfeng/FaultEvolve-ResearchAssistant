"""The candidate loop: what the local evaluator has to prove before a score can drive evolution.

Three things are pinned here and each is a separate failure mode in production. The snapshot is the
only thing a candidate sees, so it must withhold the label and the split column while still naming
the queue each row belongs to. The child process is the only place untrusted code runs, so it must
lose its credentials, its serial numbers and its clock. And the number the loop hands back has to
be the number the command line prints for the same rows - if those two ever disagree, the evolution
store is full of scores nobody can reproduce.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pandas as pd
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.smartmem import candidate_runner as runner  # noqa: E402
from benchmark.smartmem import evaluator as ev  # noqa: E402
from benchmark.smartmem import prepare_data as prep  # noqa: E402
from faultevolve.tasks.protocol import TaskSpec  # noqa: E402
from faultevolve.tasks.smartmem_adapter import SmartMemAdapter  # noqa: E402
from helpers_smartmem import write_fixture  # noqa: E402

BOUNDS = {
    "start": "2024-01-01",
    "train_until": "2024-03-01",
    "dev_until": "2024-03-20",
    "val_until": "2024-04-08",
    "outcome_observed_until": "2024-04-30",
}
EVALUATOR = Path("benchmark/smartmem/evaluator.py").resolve()

#: The simplest candidate the contract allows: name every row of the slice, once each.
CANDIDATE_ALL = """
import argparse
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("--data-dir", required=True)
parser.add_argument("--split", required=True)
parser.add_argument("--out", required=True)
args = parser.parse_args()
index = pd.read_csv(f"{args.data_dir}/{args.split}_index.csv")
frame = pd.DataFrame(
    {
        "sample_id": index["sample_id"],
        "score": [row / max(len(index) - 1, 1) for row in range(len(index))],
        "alarm": 1,
    }
)
frame.to_csv(args.out, index=False)
"""


@pytest.fixture(scope="module")
def workspace(tmp_path_factory) -> Path:
    """One prepared run directory for the module: 23 sample rows, four splits, no real data."""
    root = tmp_path_factory.mktemp("loop")
    raw = write_fixture(root / "raw")
    config = root / "split.yaml"
    config.write_text(yaml.safe_dump(BOUNDS, sort_keys=False), encoding="utf-8")
    assert (
        prep.main(
            [
                "--raw-dir", str(raw), "--out-dir", str(root / "out"), "--format", "csv",
                "--timezone", "UTC", "--split-config", str(config),
            ]
        )
        == prep.EXIT_OK
    )
    return root


@pytest.fixture
def tickets(monkeypatch, workspace) -> Path:
    """Point the environment at this run directory's label source for the whole test."""
    path = workspace / "raw" / "tickets.csv"
    monkeypatch.setenv("SMARTMEM_TICKET_FILE", str(path))
    return path


def candidate(tmp_path: Path, source: str, name: str = "solution.py") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")
    return path


def snapshot(workspace: Path, split: str, tmp_path: Path) -> Path:
    return runner.public_snapshot(workspace / "out", split, tmp_path / "snap")


# ------------------------------------------------------------------- the public snapshot


def test_snapshot_hands_out_exactly_the_four_files_the_contract_names(workspace, tmp_path):
    directory = snapshot(workspace, "dev", tmp_path)
    written = sorted(path.name for path in directory.iterdir())
    assert written == [
        "dev_index.csv",
        "dev_samples.csv.gz",
        "train_labels.csv",
        "train_samples.csv.gz",
    ]


def test_snapshot_keeps_the_label_and_the_split_off_the_rows_being_scored(workspace, tmp_path):
    directory = snapshot(workspace, "dev", tmp_path)
    query = pd.read_csv(directory / "dev_samples.csv.gz")
    assert not {"label", "split_key"} & set(query.columns)
    train = pd.read_csv(directory / "train_samples.csv.gz")
    assert not {"label", "split_key"} & set(train.columns)
    labels = pd.read_csv(directory / "train_labels.csv")
    assert list(labels.columns) == ["sample_id", "label"]
    assert set(labels["sample_id"]) == set(train["sample_id"])
    assert labels["label"].sum() > 0


def test_snapshot_index_covers_every_scored_row_and_names_its_queue(workspace, tmp_path):
    directory = snapshot(workspace, "dev", tmp_path)
    index = pd.read_csv(directory / "dev_index.csv")
    query = pd.read_csv(directory / "dev_samples.csv.gz")
    assert list(index.columns) == list(runner.INDEX_COLUMNS)
    assert set(index["sample_id"]) == set(query["sample_id"])
    assert not index["sample_id"].duplicated().any()
    assert set(index["serial_number_type"]) <= {"A", "B", runner.UNKNOWN_TYPE}
    assert set(index["serial_number_type"]) & {"A", "B"}, "the side table's queues never arrived"
    assert {"A", "B"} & set(index["serial_number_type"]), "the side table declares a queue per unit"


def test_snapshot_refuses_a_split_the_directory_does_not_hold(workspace, tmp_path):
    with pytest.raises(ValueError, match="holds no row with split_key"):
        runner.public_snapshot(workspace / "out", "holdout", tmp_path / "snap")


def test_snapshot_refuses_a_directory_that_holds_no_samples(tmp_path):
    with pytest.raises(ValueError, match="holds no sample partition"):
        runner.public_snapshot(tmp_path / "empty", "dev", tmp_path / "snap")


# ------------------------------------------------------------------- the child process


def test_execute_runs_the_command_line_the_problem_file_promise(workspace, tmp_path):
    directory = snapshot(workspace, "dev", tmp_path)
    program = candidate(tmp_path, CANDIDATE_ALL)
    out_path = tmp_path / "out.csv"
    result = runner.execute(program, directory, "dev", out_path, timeout=120)
    assert not result.timed_out
    assert result.returncode == 0
    assert result.prediction_path == out_path
    written = pd.read_csv(out_path)
    assert list(written.columns) == list(runner.OUTPUT_COLUMNS)
    assert result.duration >= 0.0


def test_execute_empties_the_environment_of_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTMEM_DEMO_API_KEY", "sup3rvisible")
    program = candidate(
        tmp_path,
        """
        import os
        for name, value in os.environ.items():
            if "sup3rvisible" in value:
                print(f"leaked {name}")
        """,
    )
    result = runner.execute(program, tmp_path, "dev", tmp_path / "out.csv", timeout=60)
    assert "sup3rvisible" not in result.output_tail
    assert "leaked" not in result.output_tail


def test_execute_swallows_a_serial_number_before_it_reaches_a_log(tmp_path):
    program = candidate(tmp_path, 'import sys\nprint("unit sn_990011 fired", file=sys.stderr)\n')
    result = runner.execute(program, tmp_path, "dev", tmp_path / "out.csv", timeout=60)
    assert "sn_990011" not in result.output_tail
    assert "[unit]" in result.output_tail


def test_execute_reports_a_timeout_instead_of_raising(tmp_path):
    program = candidate(tmp_path, "import time\ntime.sleep(5)\n")
    result = runner.execute(program, tmp_path, "dev", tmp_path / "out.csv", timeout=1)
    assert result.timed_out
    assert result.prediction_path is None


# ------------------------------------------------------------------- the loop's own verdict


def test_loop_score_is_the_command_line_score_for_the_same_rows(
    workspace, tmp_path, tickets, capsys
):
    directory = snapshot(workspace, "dev", tmp_path)
    index = pd.read_csv(directory / "dev_index.csv")
    reference = tmp_path / "predictions.csv"
    index.loc[:, ["sample_id", "prediction_time"]].to_csv(reference, index=False)
    code = ev.main(
        [
            "--run-dir", str(workspace / "out"),
            "--ticket-file", str(tickets),
            "--predictions", str(reference),
            "--split", "dev",
            "--json",
        ]
    )
    printed = capsys.readouterr().out.strip()
    assert code == ev.EXIT_OK
    payload = json.loads(printed.splitlines()[-1])

    result = ev.evaluate(
        str(candidate(tmp_path, CANDIDATE_ALL, "all.py")),
        timeout=120,
        split="dev",
        data_root=str(workspace / "out"),
    )
    assert result["validity"] == 1.0
    assert result["error_info"] == ""
    assert result["combined_score"] == pytest.approx(ev.SCORE_SCALE * payload["f_beta"])
    assert result["metric"]["event_f1"] == pytest.approx(payload["f_beta"])
    assert result["metric"]["rows_scored"] == payload["rows_scored"]
    assert result["metric"]["scored_alarms"] == payload["scored_alarms"]


def test_evaluate_refuses_a_candidate_that_reads_its_own_labels(workspace, tmp_path, tickets):
    program = candidate(tmp_path, 'import pandas as pd\npd.read_csv("ticket.csv")\n', "peek.py")
    result = ev.evaluate(
        str(program), timeout=60, split="dev", data_root=str(workspace / "out")
    )
    assert result["validity"] == 0.0
    assert "static check failed: label source" in result["error_info"]


def test_evaluate_refuses_a_candidate_that_names_a_row_it_was_never_given(
    workspace, tmp_path, tickets
):
    program = candidate(
        tmp_path,
        """
        import argparse
        import pandas as pd
        parser = argparse.ArgumentParser()
        for flag in ("--data-dir", "--split", "--out"):
            parser.add_argument(flag, required=True)
        args = parser.parse_args()
        pd.DataFrame({"sample_id": ["ghost"], "score": [0.5], "alarm": [1]}).to_csv(
            args.out, index=False
        )
        """,
        "ghost.py",
    )
    result = ev.evaluate(
        str(program), timeout=60, split="dev", data_root=str(workspace / "out")
    )
    assert result["validity"] == 0.0
    assert "name a sample_id the 'dev' index does not hold" in result["error_info"]


def test_a_row_the_candidate_declined_to_call_is_not_a_prediction(
    workspace, tmp_path, tickets, capsys
):
    """One call, written among rows that say no. The rows with ``alarm`` 0 must not reach scoring.

    Handled as a prediction they would name every unit in the slice, and a submission that says no
    everywhere would then score as if it had said yes - precision would stop measuring anything.
    """
    program = candidate(
        tmp_path,
        """
        import argparse
        import pandas as pd
        parser = argparse.ArgumentParser()
        for flag in ("--data-dir", "--split", "--out"):
            parser.add_argument(flag, required=True)
        args = parser.parse_args()
        index = pd.read_csv(f"{args.data_dir}/{args.split}_index.csv")
        frame = index.assign(score=0.5, alarm=0)
        frame.loc[0, "alarm"] = 1
        frame.loc[:, ["sample_id", "score", "alarm"]].to_csv(args.out, index=False)
        """,
        "one_call.py",
    )
    result = ev.evaluate(
        str(program), timeout=120, split="dev", data_root=str(workspace / "out")
    )
    assert result["validity"] == 1.0
    assert result["metric"]["predictions_written"] == 1
    assert result["metric"]["predictions_named"] == 1

    reference = tmp_path / "one.csv"
    index = pd.read_csv(snapshot(workspace, "dev", tmp_path / "ref") / "dev_index.csv")
    index.iloc[:1].loc[:, ["sample_id", "prediction_time"]].to_csv(reference, index=False)
    code = ev.main(
        [
            "--run-dir", str(workspace / "out"),
            "--ticket-file", str(tickets),
            "--predictions", str(reference),
            "--split", "dev",
            "--json",
        ]
    )
    assert code == ev.EXIT_OK
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["predictions_received"] == 1
    assert result["combined_score"] == pytest.approx(ev.SCORE_SCALE * payload["f_beta"])


def test_evaluate_refuses_an_alarm_value_that_is_not_a_flag(workspace, tmp_path, tickets):
    program = candidate(
        tmp_path,
        """
        import argparse
        import pandas as pd
        parser = argparse.ArgumentParser()
        for flag in ("--data-dir", "--split", "--out"):
            parser.add_argument(flag, required=True)
        args = parser.parse_args()
        index = pd.read_csv(f"{args.data_dir}/{args.split}_index.csv")
        pd.DataFrame(
            {"sample_id": [index["sample_id"][0]], "score": [0.9], "alarm": [7]}
        ).to_csv(args.out, index=False)
        """,
        "loud.py",
    )
    result = ev.evaluate(
        str(program), timeout=60, split="dev", data_root=str(workspace / "out")
    )
    assert "alarm must be 0 or 1" in result["error_info"]


def test_evaluate_refuses_the_same_row_claimed_twice(workspace, tmp_path, tickets):
    program = candidate(
        tmp_path,
        """
        import argparse
        import pandas as pd
        parser = argparse.ArgumentParser()
        for flag in ("--data-dir", "--split", "--out"):
            parser.add_argument(flag, required=True)
        args = parser.parse_args()
        index = pd.read_csv(f"{args.data_dir}/{args.split}_index.csv")
        row = index["sample_id"][0]
        pd.DataFrame(
            {"sample_id": [row, row], "score": [0.9, 0.8], "alarm": [1, 1]}
        ).to_csv(args.out, index=False)
        """,
        "twice.py",
    )
    result = ev.evaluate(
        str(program), timeout=60, split="dev", data_root=str(workspace / "out")
    )
    assert "appear on more than one output row" in result["error_info"]


def test_evaluate_tells_the_operator_when_nothing_is_prepared(tmp_path, monkeypatch):
    monkeypatch.delenv("SMARTMEM_DATA_ROOT", raising=False)
    result = ev.evaluate(
        str(candidate(tmp_path, CANDIDATE_ALL)),
        timeout=60,
        split="dev",
        data_root=str(tmp_path / "nothing"),
    )
    assert result["validity"] == 0.0
    assert "no manifest.json" in result["error_info"]


def test_evaluate_stamps_the_provisional_rule_on_every_metric(workspace, tmp_path, tickets):
    result = ev.evaluate(
        str(candidate(tmp_path, CANDIDATE_ALL, "stamp.py")),
        timeout=120,
        split="dev",
        data_root=str(workspace / "out"),
    )
    metric = result["metric"]
    assert metric["metric_status"] == ev.METRIC_SPEC_STATUS
    assert metric["duplicate_alarm_rule"] == ev.DUPLICATE_ALARM_RULES[0]
    assert metric["protocol_id"] == ev.PROTOCOL_ID
    assert metric["score_scale"] == ev.SCORE_SCALE
    assert metric["seed"] == 20260926
    assert metric["split"] == "dev"


# ------------------------------------------------------------------- the adapter's side


def test_adapter_status_names_the_layout_prepare_data_writes(workspace, monkeypatch, tickets):
    monkeypatch.setenv("SMARTMEM_DATA_ROOT", str(workspace / "out"))
    adapter = SmartMemAdapter()
    assert not any(name.startswith("public/") for name in adapter.REQUIRED_DATA_FILES)
    status = adapter.data_status(Path("benchmark/smartmem"))
    assert status.ok, status.message
    assert status.missing == []


def test_adapter_hands_the_data_root_over_as_an_argument(
    workspace, monkeypatch, tickets, tmp_path, capsys
):
    """The evaluator must not have to read the environment to find this run's data."""
    monkeypatch.delenv("SMARTMEM_DATA_ROOT", raising=False)
    adapter = SmartMemAdapter()
    adapter.data_root = lambda task_dir: workspace / "out"  # type: ignore[method-assign]
    spec = TaskSpec(
        task_dir=Path("benchmark/smartmem"),
        problem_md="",
        prompt_md="",
        init_code="",
        evaluator_path=EVALUATOR,
        config=None,
    )
    expected = _reference_f1(workspace, tickets, tmp_path, capsys)
    result = adapter.evaluate(CANDIDATE_ALL, spec, timeout=120)
    assert result.is_valid
    assert result.combined_score == pytest.approx(ev.SCORE_SCALE * expected)
    assert result.metric["protocol_id"] == ev.PROTOCOL_ID


def _reference_f1(workspace: Path, tickets: Path, tmp_path: Path, capsys) -> float:
    """Score the same rows through the command line, the number the loop has to match."""
    directory = tmp_path / "reference"
    directory.mkdir(exist_ok=True)
    index = pd.read_csv(
        runner.public_snapshot(workspace / "out", "dev", directory) / "dev_index.csv"
    )
    predictions = directory / "predictions.csv"
    index.loc[:, ["sample_id", "prediction_time"]].to_csv(predictions, index=False)
    code = ev.main(
        [
            "--run-dir", str(workspace / "out"),
            "--ticket-file", str(tickets),
            "--predictions", str(predictions),
            "--split", "dev",
            "--json",
        ]
    )
    assert code == ev.EXIT_OK
    printed = capsys.readouterr().out.strip()
    return float(json.loads(printed.splitlines()[-1])["f_beta"])


def test_adapter_constraints_replaces_the_stub_text_with_the_real_rules():
    adapter = SmartMemAdapter()
    text = adapter.constraints(None)  # type: ignore[arg-type]
    assert "暂不可用" not in text
    assert "sample_id,score,alarm" in text
    assert "SMARTMEM_TICKET" not in text


def test_static_check_refuses_the_raw_log_and_the_ticket_but_not_the_snapshot():
    assert "raw event log" in ev.static_check('import pandas as pd\npd.read_feather("x")\n')
    assert "label source" in ev.static_check("columns = ['failure_time']\n")
    assert ev.static_check('pd.read_csv(f"{a.data_dir}/train_labels.csv")\n') == ""
