"""Score a SmartMem submission against the failure tickets, at the unit level the papers use.

Three commitments shape this file. The official scoring pages record that a serial number counts
once and that a hit has to land inside the window, so that is what the default does - but the
organisers' scorer source was never obtained, so every reading that changes a number stays a flag
and the payload labels the spec ``provisional``: a score from here is comparable with another score
from here, never with somebody else's. A real serial number is a device identifier, so it is
counted or anonymised and never printed. And a slice with nothing to score is not a zero: it exits
with its own code, because reporting ``F1 = 0`` for an unlabelled window would teach a reader to
distrust every low number.

A prediction at ``t`` is credited for an alarm at ``a`` when ``a - horizon <= t <= a - lead``, the
mirror image of the label rule in ``faultevolve.data.event_sampling``. Which alarms a slice is asked
to cover is decided from the sample rows' own anchor instants, so the set of things a model could
have hit is fixed by the run directory and not by what the model submitted.

Two ways in, one of them trusted. The command line scores a submission file somebody already
produced. ``evaluate`` takes a candidate program instead, hands it the public snapshot
``candidate_runner.py`` writes, runs it in a child process, and scores the rows it claims by joining
them to the index - so the label never crosses to the side of that boundary that a candidate can
read, and the number a candidate gets is the number the command line would have printed for the same
rows.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd

from faultevolve.data.manifest import ManifestError, read_manifest
from faultevolve.tasks.smartmem_data import (
    DEFAULT_HORIZON,
    DEFAULT_LEAD,
    EPOCH_UNITS,
    SERIAL_COLUMN,
    SmartMemDataError,
    read_tickets,
)

EVALUATOR_VERSION = "smartmem-eval-v1"
#: The spec has not been confirmed by the organisers, so it is stamped on every result rather than
#: assumed: two runs of this file agree with each other, a run of this file and an official number
#: need not.
METRIC_SPEC_STATUS = "provisional"

#: 0 and 1 keep prepare_data.py's meaning. 4 is this file's own: a slice holding no labelled alarm
#: can produce no score at all, and calling that a ``0.0`` would be a lie a reader would repeat.
EXIT_OK = 0
EXIT_INPUT = 1
EXIT_NOT_SCORABLE = 4

#: The columns a run directory must carry for a prediction to be attributable to a sample row.
SAMPLE_KEY_COLUMNS = (
    "sample_id",
    "unit_id",
    "prediction_time",
    "history_end",
    "split_key",
)
PREDICTION_COLUMNS = ("sample_id", "prediction_time")
#: The three readings of "which unit did the model get right", in the order a reader should meet
#: them: the one the official pages record, then the two brackets it sits between.
DUPLICATE_ALARM_RULES = ("sn-in-window", "each-alarm", "once-per-unit")
#: Where each reading's wording comes from, printed with every score so a number cannot travel
#: without its provenance. ``sn-in-window`` is the page wording, not the organisers' scorer: their
#: source was never obtained and its licence forbids copying it in, so the status stays provisional.
RULE_PROVENANCE = {
    "sn-in-window": "one call per serial number, and a hit must land inside a window - the wording "
                    "the official scoring pages record, not their scorer, which was never obtained",
    "each-alarm": "one event per alarm, greedy in-window pairing - the local fallback protocol in "
                  "docs/plans/SMARTMEM_PHASE2_REQUIREMENTS.md 5.1",
    "once-per-unit": "one event per serial number, timing ignored - an upper bound kept to show "
                     "what the window is worth, a reading no source supports",
}
QUEUE_AGGREGATIONS = ("sum", "mean-of-f1")
#: The queue a unit lands in when neither the side table nor a ticket declares its type.
UNKNOWN_QUEUE = "unknown"
#: The side table's home inside a run directory, the partition prepare_data.py writes.
UNIT_TYPE_PARTITION = ("partitions", "units", "serial_type")
#: How many rejected rows a refusal names: enough to find the mistake, not an inventory.
SHOWN_ROWS = 5


class EvaluateError(ValueError):
    """A stop condition an operator can act on; its message is safe to print."""


class _ArgsError(Exception):
    """A command-line mistake; argparse would exit 2, which here means something else."""


class _Parser(argparse.ArgumentParser):
    """Parser that reports bad arguments through ``main`` so exit code 1 stays the input code."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise _ArgsError(message)


@dataclass(frozen=True)
class Options:
    """Everything one scoring pass needs, already converted to the types the data layer wants."""

    run_dir: Path
    ticket_file: Path
    predictions: Path
    split: str
    beta: float
    duplicate_alarm_rule: str
    queue_aggregation: str
    timezone: str
    epoch_unit: str | None
    lead: pd.Timedelta
    horizon: pd.Timedelta
    #: ``None`` reads the side table out of the run directory when one is there.
    unit_type_table: Path | None
    expect_config_hash: str | None
    json_mode: bool


class Console:
    """Where each kind of output goes; the same contract ``prepare_data.py`` keeps.

    Progress and errors always go to stderr. Stdout carries the human summary of a successful run,
    or - when ``--json`` was asked for - exactly one machine-readable object for every outcome.
    """

    def __init__(self, json_mode: bool) -> None:
        self.json_mode = json_mode

    def progress(self, message: str) -> None:
        print(f"[smartmem] {message}", file=sys.stderr)

    def emit(self, payload: dict, lines: Sequence[str]) -> None:
        if self.json_mode:
            print(json.dumps(payload, sort_keys=True, default=str))
            return
        for line in lines:
            print(line)

    def fail(self, code: int, message: str, payload: dict | None = None) -> None:
        print(message, file=sys.stderr)
        if not self.json_mode:
            return
        body = {"error": message} if payload is None else dict(payload)
        body["exit_code"] = int(code)
        print(json.dumps(body, sort_keys=True, default=str))


# ------------------------------------------------------------------- inputs


def _read_samples(run_dir: Path) -> pd.DataFrame:
    """Load the sample partitions of one run directory, keeping only the columns scoring needs."""
    directory = Path(run_dir) / "partitions" / "samples"
    files = sorted(path for path in directory.glob("*") if path.is_file())
    if not files:
        raise EvaluateError(
            f"{directory} holds no sample partition, so there is nothing to score against; run "
            "prepare_data.py in sample mode first"
        )
    joined = pd.concat([pd.read_csv(path) for path in files], ignore_index=True)
    missing = [column for column in SAMPLE_KEY_COLUMNS if column not in joined.columns]
    if missing:
        raise EvaluateError(
            f"the sample partitions do not carry {', '.join(missing)}, which scoring needs to know "
            "which row a prediction was made on and which instant that row was built for"
        )
    for column in ("prediction_time", "history_end"):
        joined[column] = pd.to_datetime(joined[column], format="ISO8601", utc=True)
    return joined.loc[:, list(SAMPLE_KEY_COLUMNS)].rename(
        columns={"prediction_time": "anchor_time"}
    )


def _read_predictions(path: Path) -> pd.DataFrame:
    """Load one submission: a ``sample_id`` and the instant the prediction was issued."""
    frame = pd.read_csv(path)
    missing = [column for column in PREDICTION_COLUMNS if column not in frame.columns]
    if missing:
        raise EvaluateError(
            f"{path} has no {', '.join(missing)} column; a prediction has to name the row it "
            "was made on and the instant it was issued"
        )
    frame["prediction_time"] = pd.to_datetime(
        frame["prediction_time"], format="ISO8601", utc=True
    )
    return frame.loc[:, list(PREDICTION_COLUMNS)]


def _read_unit_types(options: Options) -> pd.Series:
    """Map each unit to the queue its ``serial_number_type`` puts it in.

    The side table a sample run writes is the source; a ticket column is the fallback for a run
    directory predating it. A unit neither names stays in the ``unknown`` queue rather than being
    guessed, because a guess here would move a real unit between the two reported halves of the
    metric on nothing but a hunch.
    """
    path = options.unit_type_table
    if path is None:
        path = Path(options.run_dir).joinpath(*UNIT_TYPE_PARTITION)
    if Path(path).is_file():
        table = pd.read_csv(path)
        absent = [column for column in ("unit_id", "serial_number_type") if column not in table]
        if absent:
            raise EvaluateError(
                f"{path} has no {', '.join(absent)} column, so it cannot say which queue a unit is "
                "scored in"
            )
    else:
        tickets = read_tickets(
            options.ticket_file,
            timezone=options.timezone,
            epoch_unit=options.epoch_unit,
        )
        if "serial_number_type" not in tickets.columns:
            raise EvaluateError(
                f"no unit type table at {path} and {options.ticket_file} declares no "
                "serial_number_type, so the queues could not be told apart"
            )
        table = tickets.loc[:, [SERIAL_COLUMN, "serial_number_type"]].rename(
            columns={SERIAL_COLUMN: "unit_id"}
        )
    named = table.dropna(subset=["serial_number_type"]).drop_duplicates(subset=["unit_id"])
    return pd.Series(
        dict(zip(named["unit_id"].astype(str), named["serial_number_type"].astype(str)))
    )


# ------------------------------------------------------------------- validation


def _slice_rows(options: Options, samples: pd.DataFrame) -> pd.DataFrame:
    """Hand back every row of the slice this call was asked to score, predicted or not.

    The slice owns the denominator: an alarm on a unit nobody predicted is still a missed alarm, so
    a submission that ignores half the units must not be able to buy itself a recall of 1.0.
    """
    held = samples.loc[samples["split_key"].astype(str) == options.split]
    if held.empty:
        raise EvaluateError(
            f"the run directory holds no sample row with split_key {options.split!r}, so there is "
            "no slice to score; ask for a split prepare_data.py actually produced"
        )
    return held.reset_index(drop=True)


def _called_rows(
    options: Options, samples: pd.DataFrame, predictions: pd.DataFrame
) -> pd.DataFrame:
    """Pin every prediction to a sample row that could have been issued at that instant.

    Three mistakes stop the run, each named by the row that carries it: a prediction on a sample_id
    this run does not hold, a prediction on a row of a slice somebody else was asked to score, and
    a prediction issued before the row's last known event, which would score history the run says
    was not available yet. Any of them would produce a number meaning something other than what the
    model did. The submission is the left side of the join on purpose: a run directory holds rows
    nobody predicted, and those rows must not silently become predictions.
    """
    joined = predictions.merge(samples, on="sample_id", how="left")
    unknown = joined["unit_id"].isna()
    if int(unknown.sum()):
        names = ", ".join(
            sorted(str(value) for value in joined.loc[unknown, "sample_id"])[:SHOWN_ROWS]
        )
        raise EvaluateError(
            f"{int(unknown.sum())} prediction row(s) name a sample_id this run does not hold "
            f"({names}); score the run directory those predictions were made against"
        )
    foreign = joined["split_key"].astype(str) != options.split
    if int(foreign.sum()):
        names = ", ".join(
            sorted(str(value) for value in joined.loc[foreign, "sample_id"])[:SHOWN_ROWS]
        )
        raise EvaluateError(
            f"{int(foreign.sum())} prediction(s) were made on rows outside the {options.split!r} "
            f"slice ({names}); score one slice per call, because a prediction landing in another "
            "window is not this window's business"
        )
    too_early = joined["prediction_time"] < joined["history_end"]
    if int(too_early.sum()):
        names = ", ".join(
            sorted(str(value) for value in joined.loc[too_early, "sample_id"])[:SHOWN_ROWS]
        )
        raise EvaluateError(
            f"{int(too_early.sum())} prediction(s) are issued before the last event their row "
            f"claims to have seen ({names}); a prediction cannot reach back into a history the row "
            "was not built from"
        )
    return joined.reset_index(drop=True)


def _with_queue(rows: pd.DataFrame, queues: pd.Series) -> pd.DataFrame:
    """Place each row in the queue its unit's declared type puts it in, or say nobody did."""
    out = rows.copy()
    out["queue"] = out["unit_id"].astype(str).map(queues).fillna(UNKNOWN_QUEUE)
    return out


# ------------------------------------------------------------------- scoring


def _scoreable_alarms(
    rows: pd.DataFrame, alarms: pd.DataFrame, lead: pd.Timedelta, horizon: pd.Timedelta
) -> pd.DataFrame:
    """One row per ``(unit, alarm)`` this slice is asked to cover, with the instants that hit it."""
    hold = alarms.rename(columns={SERIAL_COLUMN: "unit_id"})
    pairs = hold.merge(
        rows[["unit_id", "anchor_time"]], on="unit_id", how="inner", suffixes=("", "_row")
    )
    if pairs.empty:
        return pairs.assign(hit_low=pd.Series(dtype="datetime64[ns, UTC]"))
    pairs = pairs.drop_duplicates()
    pairs["hit_low"] = pairs["failure_time"] - horizon
    pairs["hit_high"] = pairs["failure_time"] - lead
    covered = pairs["anchor_time"].between(pairs["hit_low"], pairs["hit_high"])
    return pairs.loc[covered, ["unit_id", "failure_time", "hit_low", "hit_high"]].drop_duplicates()


def _count_sn_in_window(rows: pd.DataFrame, scored: pd.DataFrame) -> dict[str, int]:
    """Count serial numbers the way the official pages word it: a unit is right once, and only if
    one of its predictions lands inside one of its windows.

    Three instants of one unit inside one window are one true positive, not one plus two false
    positives, which is what separates this from ``each-alarm``. A unit named at an instant no
    window covers is not a hit at all, which is what separates this from ``once-per-unit``. The
    denominator stays the slice's: an alarm nobody mentioned is a false negative whether or not the
    submission knew the unit existed.
    """
    positive = {str(unit) for unit in scored["unit_id"]}
    predicted = {str(unit) for unit in rows["unit_id"]}
    hit: set[str] = set()
    if positive and predicted:
        pairing = rows.merge(scored, on="unit_id", how="inner", suffixes=("", "_alarm"))
        inside = pairing["prediction_time"].between(pairing["hit_low"], pairing["hit_high"])
        hit = {str(unit) for unit in pairing.loc[inside, "unit_id"]}
    return {"tp": len(hit), "fp": len(predicted - hit), "fn": len(positive - hit)}


def _count_each_alarm(rows: pd.DataFrame, scored: pd.DataFrame) -> dict[str, int]:
    """Each alarm is its own event: greedy match, oldest prediction against the earliest window.

    The fallback protocol ``docs/plans/SMARTMEM_PHASE2_REQUIREMENTS.md`` 5.1 asks for while no
    reference scorer exists, and the tightest of the three readings."""
    windows = {
        str(unit): sorted(group[["hit_low", "hit_high"]].itertuples(index=False))
        for unit, group in scored.groupby("unit_id", sort=False)
    }
    taken: dict[str, set[int]] = {}
    true_positive = 0
    for unit, group in rows.groupby("unit_id", sort=False):
        name = str(unit)
        held = windows.get(name, [])
        used = taken.setdefault(name, set())
        for moment in sorted(group["prediction_time"]):
            index = next(
                (
                    position
                    for position, window in enumerate(held)
                    if position not in used and window.hit_low <= moment <= window.hit_high
                ),
                None,
            )
            if index is not None:
                used.add(index)
                true_positive += 1
    alarms = int(len(scored))
    predictions = int(len(rows))
    return {"tp": true_positive, "fp": predictions - true_positive, "fn": alarms - true_positive}


def _count_once_per_unit(rows: pd.DataFrame, scored: pd.DataFrame) -> dict[str, int]:
    """Each unit is one event, whatever its timing: a prediction on a unit is a positive call.

    This is the loosest of the three readings and it is kept only to measure what the window is
    worth - it asks whether the model named the units that failed, so a prediction issued at an
    instant no window covers still counts. Nothing in the recorded wording supports it, which is why
    it is a flag and never the default.
    """
    positive = {str(unit) for unit in scored["unit_id"]}
    predicted = {str(unit) for unit in rows["unit_id"]}
    return {
        "tp": len(positive & predicted),
        "fp": len(predicted - positive),
        "fn": len(positive - predicted),
    }


def _prf(counts: dict[str, int], beta: float) -> dict[str, object]:
    """Precision, recall and F-beta from one set of counts; an empty side is reported as null."""
    true_positive, false_positive, false_negative = counts["tp"], counts["fp"], counts["fn"]
    predicted = true_positive + false_positive
    actual = true_positive + false_negative
    precision = true_positive / predicted if predicted else None
    recall = true_positive / actual if actual else None
    if not precision or not recall:
        f_beta = 0.0
    else:
        square = float(beta) ** 2
        f_beta = (1.0 + square) * precision * recall / (square * precision + recall)
    return {
        "tp": int(true_positive),
        "fp": int(false_positive),
        "fn": int(false_negative),
        "alarms": int(actual),
        "predictions": int(predicted),
        "precision": None if precision is None else round(precision, 6),
        "recall": None if recall is None else round(recall, 6),
        "f_beta": round(float(f_beta), 6),
    }


COUNTERS = {
    "sn-in-window": _count_sn_in_window,
    "each-alarm": _count_each_alarm,
    "once-per-unit": _count_once_per_unit,
}


def _score(
    options: Options, selection: pd.DataFrame, called: pd.DataFrame, alarms: pd.DataFrame
) -> dict[str, object]:
    """Score each queue on its own, then combine the queues the way the flag says.

    The loop runs over the queues present in the slice, not over the ones the submission touched: a
    queue nobody predicted still holds alarms, and those are false negatives somebody owes the
    report. ``sum`` is the reading the recorded wording implies, because it states precision and
    recall over the serial numbers as one set; ``mean-of-f1`` is kept because averaging the two
    queues' F weights a queue of three units the same as a queue of three hundred.
    """
    counter = COUNTERS[options.duplicate_alarm_rule]
    per_queue: dict[str, dict[str, object]] = {}
    for queue, group in selection.groupby("queue", sort=True):
        name = str(queue)
        hold = alarms.loc[
            alarms[SERIAL_COLUMN].astype(str).isin({str(unit) for unit in group["unit_id"]})
        ]
        scored = _scoreable_alarms(group, hold, options.lead, options.horizon)
        counts = counter(called.loc[called["queue"] == name], scored)
        per_queue[name] = _prf(counts, options.beta)
    buckets = list(per_queue.values())
    combined = _prf(
        {
            "tp": sum(int(bucket["tp"]) for bucket in buckets),
            "fp": sum(int(bucket["fp"]) for bucket in buckets),
            "fn": sum(int(bucket["fn"]) for bucket in buckets),
        },
        options.beta,
    )
    if options.queue_aggregation == "mean-of-f1":
        # A queue with neither an alarm nor a prediction has no F1 of its own, so it does not get a
        # vote: averaging it in as a zero would punish a split for being clean.
        held = [bucket for bucket in buckets if int(bucket["alarms"]) or int(bucket["predictions"])]
        if held:
            overall = round(sum(float(b["f_beta"]) for b in held) / len(held), 6)
        else:
            overall = None
    else:
        overall = combined["f_beta"]
    return {
        "queues": per_queue,
        "totals": {key: value for key, value in combined.items()},
        "f_beta": overall,
    }


# ------------------------------------------------------------------- reporting


def _human_lines(options: Options, payload: dict) -> list[str]:
    totals = payload["totals"]
    lines = [
        f"split {options.split}: {payload['rows_scored']} row(s) in the slice, of which "
        f"{payload['predictions_received']} carry a prediction; {totals['alarms']} alarm(s) this "
        "slice must cover",
        f"F({float(options.beta):g}) = {payload['f_beta']} "
        f"({options.queue_aggregation} over {', '.join(sorted(payload['queues']))})",
        f"counts: tp={totals['tp']} fp={totals['fp']} fn={totals['fn']} "
        f"(rule: {options.duplicate_alarm_rule})",
        f"rule provenance: {payload['rule_provenance']}",
    ]
    for queue, bucket in sorted(payload["queues"].items()):
        lines.append(
            f"  queue {queue}: tp={bucket['tp']} fp={bucket['fp']} fn={bucket['fn']} "
            f"F = {bucket['f_beta']}"
        )
    lines.append(
        f"metric_spec_status: {METRIC_SPEC_STATUS} - comparable with another run of this file only"
    )
    if payload["unknown_type_units"]:
        lines.append(
            f"{payload['unknown_type_units']} scored row(s) carry no declared serial_number_type "
            f"and were counted in the {UNKNOWN_QUEUE} queue"
        )
    return lines


def _not_scorable(console: Console, options: Options, reason: str, rows: int) -> int:
    console.fail(
        EXIT_NOT_SCORABLE,
        f"the {options.split!r} slice has nothing to score ({reason}), so no F1 is reported rather "
        "than a zero one",
        {"exit_code": EXIT_NOT_SCORABLE, "scoreable": False, "reason": reason, "rows_scored": rows},
    )
    return EXIT_NOT_SCORABLE


def _report(options: Options, console: Console) -> int:
    manifest = read_manifest(options.run_dir)
    if options.expect_config_hash and manifest["config_hash"] != options.expect_config_hash:
        raise EvaluateError(
            f"{options.run_dir} records config_hash {manifest['config_hash'][:12]}…, this call "
            f"asked for {options.expect_config_hash[:12]}…; the predictions and the sample table "
            "would describe two different runs"
        )
    samples = _read_samples(options.run_dir)
    tickets = read_tickets(
        options.ticket_file, timezone=options.timezone, epoch_unit=options.epoch_unit
    )
    predictions = _read_predictions(options.predictions)
    queues = _read_unit_types(options)
    selection = _with_queue(_slice_rows(options, samples), queues)
    called = _with_queue(_called_rows(options, samples, predictions), queues)
    alarms = tickets.dropna(subset=["failure_time"])
    if alarms.empty:
        return _not_scorable(console, options, "the ticket file holds no alarm", len(selection))
    result = _score(options, selection, called, alarms)
    if not int(result["totals"]["alarms"]):
        return _not_scorable(
            console,
            options,
            "no alarm falls inside a label window of this slice, so every row here is a negative "
            "nobody could have been asked about",
            len(selection),
        )
    payload = {
        "evaluator_version": EVALUATOR_VERSION,
        "metric_spec_status": METRIC_SPEC_STATUS,
        "exit_code": EXIT_OK,
        "scoreable": True,
        "config_hash": manifest["config_hash"],
        "split": options.split,
        "beta": float(options.beta),
        "duplicate_alarm_rule": options.duplicate_alarm_rule,
        "rule_provenance": RULE_PROVENANCE[options.duplicate_alarm_rule],
        "queue_aggregation": options.queue_aggregation,
        "lead": str(options.lead),
        "horizon": str(options.horizon),
        "rows_scored": int(len(selection)),
        "units_scored": int(selection["unit_id"].nunique()),
        "predictions_received": int(len(called)),
        "scored_alarms": int(result["totals"]["alarms"]),
        "unknown_type_units": int((selection["queue"] == UNKNOWN_QUEUE).sum()),
        **result,
    }
    console.emit(payload, _human_lines(options, payload))
    return EXIT_OK


# ------------------------------------------------------------------- candidate loop


#: What a candidate writes: which rows it fires on. The instant of an alarm is never the
#: candidate's to claim - section 4.2 of ``docs/plans/SMARTMEM_PHASE2_REQUIREMENTS.md`` has the
#: evaluator join the row to its anchor, and ``_candidate_predictions`` below is that join.
CANDIDATE_OUTPUT_COLUMNS = ("sample_id", "score", "alarm")
#: Stamped on every metric, so a score cannot travel without the rules that produced it.
PROTOCOL_ID = "smartmem-local-protocol-v1"
#: The loop optimises a 0-100 number, the convention every other Famou task in this repository
#: uses; ``event_f1`` in the same payload stays on the 0-1 scale the papers quote.
SCORE_SCALE = 100.0

DATA_ROOT_ENV = "SMARTMEM_DATA_ROOT"
TICKET_FILE_ENV = "SMARTMEM_TICKET_FILE"
TICKET_EPOCH_ENV = "SMARTMEM_TICKET_EPOCH_UNIT"

#: What a candidate must not reach for. ``faultevolve.common.codecheck`` already refuses path
#: climbing, directory listing and subprocess; these two buckets refuse the label source and the
#: raw event log, both of which a candidate could name outright inside a path it was handed.
CANDIDATE_FORBIDDEN = {
    "label source": (
        r"failure_ticket|tickets?\.csv|\bfailure_time\b|\balarm_time\b|\bsn_name\b|\bsn_type\b"
        r"|label_window"
    ),
    "raw event log": r"\.feather\b|read_feather|\bmcelog\b",
}


def static_check(source: str) -> str:
    """Refuse candidates that read their own answer or the log the snapshot was built from."""
    for lineno, line in enumerate(source.splitlines(), 1):
        code_part = line.split("#", 1)[0]
        for reason, pattern in CANDIDATE_FORBIDDEN.items():
            if re.search(pattern, code_part):
                return f"{reason} (line {lineno}): {code_part.strip()[:120]}"
    return ""


def _runner():
    """Import the sibling helper; this file is loaded by path, so its directory is no package."""
    directory = str(Path(__file__).resolve().parent)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    import candidate_runner

    return candidate_runner


def resolve_data_root(data_root: str | Path | None = None) -> Path:
    """An explicit run directory, then ``SMARTMEM_DATA_ROOT``, then this task's own ``data``."""
    if data_root is not None:
        return Path(data_root)
    env = os.environ.get(DATA_ROOT_ENV)
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "data"


def resolve_ticket_file(run_dir: Path, ticket_file: str | Path | None = None) -> Path:
    """Find the label source: an explicit path, then the environment, then the run directory.

    A manifest records the ticket's hash but not where the file sits, so a prepared run directory
    cannot point at its own labels; the bare names tried here are the ones ``prepare_data.py``
    scans for when it builds a directory.
    """
    candidates: list[Path] = []
    if ticket_file is not None:
        candidates = [Path(ticket_file)]
    elif os.environ.get(TICKET_FILE_ENV):
        candidates = [Path(str(os.environ.get(TICKET_FILE_ENV)))]
    else:
        from prepare_data import TICKET_NAMES

        candidates = [
            Path(run_dir) / name for name in TICKET_NAMES
        ] + [Path(run_dir).parent / name for name in TICKET_NAMES]
    for path in candidates:
        if path.is_file():
            return path
    tried = ", ".join(str(path) for path in candidates[:4])
    raise EvaluateError(
        f"no label source found (looked for {tried}); point {TICKET_FILE_ENV} at the ticket table "
        f"{run_dir} was labelled with, because without it nothing here can be scored"
    )


def _ticket_epoch_unit() -> str | None:
    """The declared instant dialect of the ticket table, or ``None`` when it carries timestamps."""
    env = os.environ.get(TICKET_EPOCH_ENV)
    if not env:
        return None
    if env not in EPOCH_UNITS:
        raise EvaluateError(
            f"{TICKET_EPOCH_ENV}={env!r} is not one of {EPOCH_UNITS}; digits alone cannot say "
            "whether an instant is seconds or milliseconds"
        )
    return str(env)


def _candidate_predictions(
    frame: pd.DataFrame, index: pd.DataFrame, split: str
) -> pd.DataFrame:
    """Turn "these rows fire" into the table scoring reads: a sample_id and its row's own instant.

    A row with ``alarm`` 0 is dropped rather than carried as a negative: precision counts the units
    a submission named, so a row it never claimed is not part of that denominator. The ``score``
    column is required by the contract and left unread here, because none of the three provisional
    counting rules ranks calls against each other.
    """
    missing = [column for column in CANDIDATE_OUTPUT_COLUMNS if column not in frame.columns]
    if missing:
        raise EvaluateError(
            f"the candidate's output has no {', '.join(missing)} column; the contract is "
            f"{', '.join(CANDIDATE_OUTPUT_COLUMNS)}"
        )
    alarm = pd.to_numeric(frame["alarm"], errors="coerce")
    if not alarm.dropna().isin((0, 1)).all():
        raise EvaluateError("alarm must be 0 or 1 on every row the candidate writes")
    duplicated = int(frame["sample_id"].duplicated().sum())
    if duplicated:
        raise EvaluateError(
            f"{duplicated} sample_id value(s) appear on more than one output row; one row per "
            "prediction, or the count of calls a submission made stops meaning anything"
        )
    fired = frame.loc[alarm == 1]
    scores = pd.to_numeric(frame["score"], errors="coerce")
    if not fired.empty and bool(scores.loc[fired.index].isna().any()):
        raise EvaluateError("every row with alarm 1 has to carry a numeric score")
    joined = fired.loc[:, ["sample_id"]].merge(index, on="sample_id", how="left")
    unknown = joined["prediction_time"].isna()
    if int(unknown.sum()):
        names = ", ".join(
            sorted(str(value) for value in joined.loc[unknown, "sample_id"])[:SHOWN_ROWS]
        )
        raise EvaluateError(
            f"{int(unknown.sum())} prediction(s) name a sample_id the {split!r} index does not "
            f"hold ({names}); predict only on the rows the snapshot handed you"
        )
    return joined.loc[:, ["sample_id", "prediction_time"]]


def _score_in_process(options: Options) -> tuple[int, dict | None]:
    """Run one scoring pass and read back the payload the command line would have printed.

    In-process on purpose: a candidate has already had its own child process, and a second one here
    would re-read every partition for nothing. The stdout detour is the existing ``Console``
    contract, so the number scored here and the number ``--json`` prints cannot drift.
    """
    console = Console(json_mode=True)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = _report(options, console)
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    if not lines:
        return code, None
    return code, json.loads(lines[-1])


def evaluate(
    program_path: str,
    timeout: int = 900,
    split: str = "dev",
    *,
    data_root: str | Path | None = None,
    seed: int = 20260926,
    ticket_file: str | Path | None = None,
) -> dict[str, object]:
    """Run one candidate on one split of one prepared run directory, then score what it writes.

    The order is the one the protocol fixes: static check, snapshot, child process, output check,
    key join, scoring, then the teardown the ``with`` block guarantees. ``seed`` is recorded on the
    metric rather than consumed - nothing in this function draws a random number, and the only
    randomness in a score is what the candidate does with it. A ``validity`` of 0 always comes with
    an ``error_info`` an operator can act on, and never with a score that would be averaged.
    """
    started = time.monotonic()
    context: dict[str, object] = {
        "protocol_id": PROTOCOL_ID,
        "metric_status": METRIC_SPEC_STATUS,
        "score_scale": SCORE_SCALE,
        "duplicate_alarm_rule": DUPLICATE_ALARM_RULES[0],
        "evaluator_version": EVALUATOR_VERSION,
    }

    def outcome(validity: float, score: float, error: str, metric: dict | None = None) -> dict:
        return {
            "validity": float(validity),
            "combined_score": float(score),
            "cost_time": round(time.monotonic() - started, 3),
            "error_info": error,
            "metric": {"split": str(split), "seed": int(seed), **context, **(metric or {})},
        }

    program = Path(program_path)
    if not program.is_file():
        return outcome(0.0, 0.0, f"candidate not found: {program}")
    try:
        source = program.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return outcome(0.0, 0.0, f"candidate unreadable: {exc}")
    violation = static_check(source)
    if violation:
        return outcome(0.0, 0.0, f"static check failed: {violation}")

    run_dir = resolve_data_root(data_root)
    if not (run_dir / "manifest.json").is_file():
        return outcome(
            0.0,
            0.0,
            f"{run_dir} holds no manifest.json, so it is not a prepared run directory; point "
            f"{DATA_ROOT_ENV} at prepare_data.py's output",
        )
    try:
        tickets = resolve_ticket_file(run_dir, ticket_file)
        epoch_unit = _ticket_epoch_unit()
    except EvaluateError as exc:
        return outcome(0.0, 0.0, str(exc))

    runner = _runner()
    with tempfile.TemporaryDirectory(prefix="smartmem-eval-") as tmp:
        staging = Path(tmp) / "data"
        try:
            runner.public_snapshot(run_dir, split, staging)
        except ValueError as exc:
            return outcome(0.0, 0.0, f"snapshot failed: {exc}")
        out_path = Path(tmp) / "candidate_output.csv"
        result = runner.execute(program, staging, split, out_path, timeout=timeout)
        timing = {"run_time_s": result.duration}
        if result.timed_out:
            return outcome(
                0.0,
                0.0,
                f"candidate timed out after {timeout}s: {result.output_tail[-500:]}",
                timing,
            )
        if result.returncode != 0:
            return outcome(
                0.0,
                0.0,
                f"candidate exited with code {result.returncode}: {result.output_tail[-500:]}",
                timing,
            )
        if result.prediction_path is None:
            return outcome(0.0, 0.0, "candidate wrote no output file", timing)
        try:
            written = pd.read_csv(result.prediction_path)
            index = pd.read_csv(staging / f"{split}_index.csv")
            predictions = _candidate_predictions(written, index, split)
        except (EvaluateError, ValueError, OSError) as exc:
            return outcome(0.0, 0.0, f"{type(exc).__name__}: {exc}", timing)
        predictions_path = Path(tmp) / "predictions.csv"
        predictions.to_csv(predictions_path, index=False)
        options = Options(
            run_dir=run_dir,
            ticket_file=tickets,
            predictions=predictions_path,
            split=str(split),
            beta=1.0,
            duplicate_alarm_rule=DUPLICATE_ALARM_RULES[0],
            queue_aggregation="sum",
            timezone="UTC",
            epoch_unit=epoch_unit,
            lead=DEFAULT_LEAD,
            horizon=DEFAULT_HORIZON,
            unit_type_table=None,
            expect_config_hash=None,
            json_mode=True,
        )
        try:
            code, payload = _score_in_process(options)
        except (EvaluateError, SmartMemDataError, ManifestError, OSError, ValueError) as exc:
            return outcome(0.0, 0.0, f"{type(exc).__name__}: {exc}", timing)
        if code != EXIT_OK or payload is None:
            reason = "" if payload is None else str(payload.get("reason", ""))
            return outcome(
                0.0,
                0.0,
                f"the {split!r} slice produced no score (exit {code}): {reason} - an unscored "
                "slice is not a zero, so this candidate is invalid rather than bad",
                {**timing, "predictions_written": int(len(predictions))},
            )
        totals = payload["totals"]
        event_f1 = payload["f_beta"]
        metric = {
            **timing,
            "event_f1": event_f1,
            "f1": event_f1,
            "precision": totals["precision"],
            "recall": totals["recall"],
            "tp": totals["tp"],
            "fp": totals["fp"],
            "fn": totals["fn"],
            "alarms": totals["alarms"],
            "predictions_named": totals["predictions"],
            "predictions_written": int(len(predictions)),
            "beta": float(options.beta),
            "config_hash": payload["config_hash"],
            "rows_scored": payload["rows_scored"],
            "units_scored": payload["units_scored"],
            "scored_alarms": payload["scored_alarms"],
            "queues": sorted(str(name) for name in payload["queues"]),
        }
        score = 0.0 if event_f1 is None else SCORE_SCALE * float(event_f1)
        return outcome(1.0, score, "", metric)


# ------------------------------------------------------------------- entry point


def _duration(value: str) -> pd.Timedelta:
    try:
        return pd.Timedelta(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a duration pandas understands (try 15m or 7D)"
        ) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="evaluator.py",
        description="Score a SmartMem prediction file against the failure tickets.",
    )
    parser.add_argument("--run-dir", required=True, type=Path, help="a prepare_data.py output")
    parser.add_argument("--ticket-file", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--split", required=True, help="the split_key to score, usually dev or val")
    parser.add_argument("--beta", type=float, default=1.0)
    parser.add_argument(
        "--duplicate-alarm-rule",
        choices=DUPLICATE_ALARM_RULES,
        default=DUPLICATE_ALARM_RULES[0],
        help="which reading of a hit to score by: sn-in-window is the wording the official pages "
        "record, each-alarm and once-per-unit are the tight and loose brackets (all provisional)",
    )
    parser.add_argument(
        "--queue-aggregation",
        choices=QUEUE_AGGREGATIONS,
        default="sum",
        help="how the two serial number queues combine into one number; sum is what the recorded "
        "wording implies, mean-of-f1 the sensitivity check (provisional)",
    )
    parser.add_argument("--lead", type=_duration, default=DEFAULT_LEAD)
    parser.add_argument("--horizon", type=_duration, default=DEFAULT_HORIZON)
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--epoch-unit", choices=EPOCH_UNITS, default=None)
    parser.add_argument(
        "--unit-type-table",
        type=Path,
        default=None,
        help="a unit -> serial_number_type table; defaults to the one inside --run-dir",
    )
    parser.add_argument(
        "--expect-config-hash",
        default=None,
        help="refuse to score unless the run directory records this config hash",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def _options(args: argparse.Namespace) -> Options:
    return Options(
        run_dir=Path(args.run_dir),
        ticket_file=Path(args.ticket_file),
        predictions=Path(args.predictions),
        split=str(args.split),
        beta=float(args.beta),
        duplicate_alarm_rule=str(args.duplicate_alarm_rule),
        queue_aggregation=str(args.queue_aggregation),
        timezone=str(args.timezone),
        epoch_unit=args.epoch_unit,
        lead=args.lead,
        horizon=args.horizon,
        unit_type_table=None if args.unit_type_table is None else Path(args.unit_type_table),
        expect_config_hash=(
            None if args.expect_config_hash is None else str(args.expect_config_hash)
        ),
        json_mode=bool(args.json),
    )


def main(argv: list[str] | None = None) -> int:
    words = list(sys.argv[1:] if argv is None else argv)
    console = Console("--json" in words)
    try:
        options = _options(_build_parser().parse_args(words))
        if options.beta <= 0:
            raise EvaluateError("--beta has to be a positive number; F-beta is undefined at 0")
        return _report(options, console)
    except (_ArgsError, EvaluateError, SmartMemDataError, ManifestError, OSError) as exc:
        console.fail(EXIT_INPUT, f"{type(exc).__name__}: {exc}")
        return EXIT_INPUT


__all__ = [
    "CANDIDATE_OUTPUT_COLUMNS",
    "DUPLICATE_ALARM_RULES",
    "EVALUATOR_VERSION",
    "EXIT_INPUT",
    "EXIT_NOT_SCORABLE",
    "EXIT_OK",
    "EvaluateError",
    "METRIC_SPEC_STATUS",
    "PROTOCOL_ID",
    "QUEUE_AGGREGATIONS",
    "RULE_PROVENANCE",
    "Options",
    "evaluate",
    "main",
    "static_check",
]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
