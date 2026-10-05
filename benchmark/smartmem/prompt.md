# Role

You are an expert in memory reliability engineering and machine learning for predictive
maintenance. You improve a Python program that predicts DRAM uncorrectable errors (UE) from
mcelog event streams.

# Task

For every sample row of a query set (one row = one memory serial number at one 15-minute grid
instant), decide whether that serial number will be replaced by a failure ticket within the next
7 days, and raise an alarm when it will. Only events at or before the row's own instant exist in its
features; nothing after it may be used.

The program is run as:

    python solution.py --data-dir <abs_dir> --split <dev|val> --out <abs_csv>

It must write a CSV with columns `sample_id, score, alarm`, exactly one row per `sample_id` in
`<split>_index.csv`. `score` is a finite number (higher = more likely to fail); it is diagnostic
only. `alarm` is an integer 0 or 1, and it is the scored input. The evaluator takes the alarm
instant from the index row, so a program never reports timestamps or hardware types itself.

# Data

Files inside `--data-dir` (open them only by these exact names):

- `train_samples.csv.gz`: training-slice rows with feature columns, no `label`
- `train_labels.csv`: `sample_id, label`, censoring-audited training rows only
- `<split>_index.csv`: `sample_id, unit_id, prediction_time, history_end, serial_number_type`
- `<split>_samples.csv.gz`: query rows with feature columns, no `label`, no `split_key`

Feature columns are aggregates of the mcelog history inside the row's lookback window: CE counts
split by read and scrub errors, event count with the recent/earlier half-window split, growth rate,
minutes since the last event, distinct id counts and repetition shares at CPU / channel / DIMM /
rank / device / bank group / bank / row / column level, parity and retry-log mark rates, burst-info
cardinality, the last error type, the static hardware profile columns, and two coverage columns
describing how much of the window the unit actually filled.

Data facts that shape the problem: UE is rare in the field, yet the sampled rows are far denser in
positives (about a quarter in the 200-unit slice this task was built on), so a threshold tuned on
row density does not transfer to a fleet alert budget. Tickets in the current slice are all queue
A; queue B has no alarms yet, so per-queue behaviour cannot be measured here.

# Score (maximize)

combined_score = 100 * F, where F is the SN-level event F-score over the scored slice

A prediction for a serial number counts as a hit for a ticket at `a` when it lands inside
`[a - 7d, a - 15min]`; those two offsets are fixed official values. Serial numbers are counted once
each: `precision = hit SN / predicted SN`, `recall = hit SN / ticketed SN in this slice`, and
`F = (1 + beta^2) * P * R / (beta^2 * P + R)` with `beta = 1` by default. Naming a serial number
several times therefore costs nothing - the only lever on precision is *which* serial numbers are
named at all. Time cost is reported separately and is not multiplied into the score.

The spec label on every result is `provisional`: the organisers' scorer source was never obtained.
A score here is comparable with another score here, never with a leaderboard number. Because the
dedup rule ignores how many rows a unit fires, a submission that names every alarmed unit scores
perfectly on the reference slice - which is exactly why an alert budget, not the pairing rule, is
the open question in this task's notes.

# Hard constraints

- Finish within 900 seconds including training; use only pandas, numpy, scikit-learn, lightgbm,
  scipy.
- Do not read anything except the four files above; no `..`, `.parent`, glob/listdir/walk/iterdir,
  cwd access, subprocess, network, or environment secrets. Such code is rejected with score 0.
- Do not use information after a row's instant; do not hard-code or print serial numbers.
- Cover every index `sample_id` exactly once, with finite scores and 0/1 alarms.

# Reference feasible solution

The initial program fits a class-balanced logistic regression on fifteen CE count, trend and
spatial-concentration columns, calls each serial number at its single most urgent row, and sets the
alarm cut as a **percentile** of the loudest-row distribution - chosen on the training slice by an
SN-level proxy F1 and re-applied to the query slice. An absolute probability cut does not survive
the density shift between slices (on the 200-unit slice it silenced every dev alarm). It is a
starting point defined by this repository, not an official baseline and not a claim about
achievable score. Promising directions: separating temporal clustering (CE storms, growth,
recency) from spatial clustering (repeats within one row/bank versus spread across many),
long-horizon cumulative counts instead of short windows, queue- or profile-specific thresholds,
alert-budget-driven cutoffs, and censoring-aware labelling.
