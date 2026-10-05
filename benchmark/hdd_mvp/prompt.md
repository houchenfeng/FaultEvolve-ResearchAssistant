# Role

You are an expert in storage reliability engineering and machine learning for
predictive maintenance. You improve a Python program that predicts hard-disk
failures from SMART telemetry.

# Task

For every disk in the query set, predict whether it fails within the next 7 days
after its cutoff date, using at most 14 days of daily SMART history that ends on
the cutoff date. Output a ranking score and a binary alarm per disk.

The program is run as:

    python solution.py --data-dir <abs_dir> --split <val|test> --out <abs_csv>

It must write a CSV with columns `serial_number, score, alarm`, exactly one row per
disk listed in `<split>_index.csv`. `score` is a finite number (higher = more likely
to fail). `alarm` is 0 or 1.

# Data

Files inside `--data-dir` (open them only by these exact names):

- `train_history.csv.gz`: daily snapshots of training disks
- `train_labels.csv`: `serial_number, model, cutoff_date, label, weight`
- `<split>_history.csv.gz`: daily snapshots of query disks; each disk's last row is its cutoff day
- `<split>_index.csv`: `serial_number, model, cutoff_date`

History columns: `date, serial_number, model, capacity_bytes`, SMART raw columns
`smart_<id>_raw` for ids 1,3,4,5,7,9,10,12,187,188,190,191,192,193,194,196,197,198,199,240,241,242
and normalized columns `smart_<id>_normalized` for ids 1,3,5,7,9,187,194,197,198.
Attribute availability differs by vendor (e.g. 187/188/190 are mostly Seagate); missing values are empty.
Negative training samples are subsampled; `weight` is how many real healthy disks each one represents
(about 10). Positives have weight 1. Failure prevalence in the real fleet is about 0.25%.

# Score (maximize)

combined_score = 100 * (0.5 * F1_p10 + 0.3 * AUPRC + 0.2 * Recall@FAR<=0.2%) * min(1, 600 / runtime_s)

All metrics are weighted by `weight`. F1_p10 is the 10th percentile of bootstrap F1 of the
`alarm` column, so thresholds must be robust, not lucky. AUPRC and Recall@FAR use `score`.

# Hard constraints

- Finish within 900 seconds including training; use only pandas, numpy, scikit-learn, lightgbm, scipy.
- Do not read anything except the four files above; no `..`, `.parent`, glob/listdir/walk/iterdir,
  cwd access, subprocess, or network. Such code is rejected with score 0.
- Do not use information after the cutoff date; do not hard-code serial numbers.

# Reference feasible solution

The initial program trains a class-weighted logistic regression on log1p of ten cutoff-day
SMART values plus vendor one-hot features and picks the alarm threshold that maximizes weighted
F1 on the training set (validation combined_score about 22.8). Promising directions: temporal
trend and change features over the 14-day window, vendor/model-aware features, gradient-boosted
trees, out-of-fold threshold selection, calibrated alarm policies, and imbalance handling.
