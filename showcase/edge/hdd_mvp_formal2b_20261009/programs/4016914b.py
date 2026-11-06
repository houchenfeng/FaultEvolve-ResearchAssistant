import argparse
import os
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import StratifiedKFold

RAW_ATTRS = [
    1, 3, 4, 5, 7, 9, 10, 12,
    187, 188, 190, 191, 192, 193, 194,
    196, 197, 198, 199, 241, 242
]
NORM_ATTRS = [5, 187, 194, 197, 198]
CRITICAL_RAW = [5, 187, 188, 197, 198, 199]
MONOTONIC_RAW = {4, 5, 9, 10, 12, 187, 188, 191, 192, 193, 196, 197, 198, 199, 241, 242}
MONOTONIC_RAW_COLS = {f"smart_{i}_raw" for i in MONOTONIC_RAW}
VENDORS = ["ST", "TOSHIBA", "HGST", "HITACHI", "WDC", "SAMSUNG", "MAXTOR", "QUANTUM", "FUJITSU"]
BASE_COLS = ["date", "serial_number", "capacity_bytes"]
META_COLS = [
    "snap_count",
    "window_span_days",
    "days_last_to_cutoff",
    "days_first_to_cutoff",
    "avg_gap_days",
    "snap_ratio",
    "capacity_log",
] + [f"vendor_{v}" for v in VENDORS] + ["vendor_other"]

CONFIGS = [
    {
        "num_leaves": 31,
        "min_child_samples": 30,
        "learning_rate": 0.035,
        "n_estimators": 300,
        "pos_boost": 1.0,
    },
    {
        "num_leaves": 15,
        "min_child_samples": 50,
        "learning_rate": 0.05,
        "n_estimators": 300,
        "pos_boost": 2.0,
    },
]


def smart_columns():
    raw = [f"smart_{i}_raw" for i in RAW_ATTRS]
    norm = [f"smart_{i}_normalized" for i in NORM_ATTRS]
    return raw + norm


def read_history(path):
    needed = set(smart_columns())
    base = set(BASE_COLS)
    dtype = {c: "float32" for c in needed}
    dtype["serial_number"] = "category"
    dtype["capacity_bytes"] = "float32"
    return pd.read_csv(
        path,
        usecols=lambda c: c in base or c in needed,
        parse_dates=["date"],
        dtype=dtype,
    )


def add_vendor_from_cutoffs(x, cutoffs):
    if "model" in cutoffs.columns and "serial_number" in cutoffs.columns:
        model_map = dict(
            zip(
                cutoffs["serial_number"].astype("object"),
                cutoffs["model"].astype("object").fillna(""),
            )
        )
    else:
        model_map = {}
    models = pd.Series(x.index.map(model_map), index=x.index, dtype="object").fillna("")
    total = np.zeros(len(x), dtype="float32")
    for v in VENDORS:
        val = models.str.startswith(v).astype("float32")
        x[f"vendor_{v}"] = val
        total += val.to_numpy()
    x["vendor_other"] = np.maximum(0.0, 1.0 - total).astype("float32")


def zero_features(target_sn, cutoffs):
    x = pd.DataFrame(index=pd.Index(target_sn, name="serial_number"))
    for c in META_COLS:
        x[c] = 0.0
    add_vendor_from_cutoffs(x, cutoffs)
    return x.astype("float32")


def build_features(hist, cutoffs):
    cutoffs = cutoffs.drop_duplicates(subset=["serial_number"], keep="last")
    target_sn = cutoffs["serial_number"].astype("object").unique()
    if len(target_sn) == 0:
        return pd.DataFrame()

    if hist.empty:
        return zero_features(target_sn, cutoffs)

    cutoff_map = dict(
        zip(cutoffs["serial_number"].astype("object"), cutoffs["cutoff_date"])
    )
    hist["cutoff_date"] = hist["serial_number"].map(cutoff_map)
    hist = hist[hist["date"].notna() & hist["cutoff_date"].notna()]
    hist = hist[hist["date"] <= hist["cutoff_date"]]
    hist = hist[hist["date"] >= hist["cutoff_date"] - pd.Timedelta(days=13)]

    if hist.empty:
        return zero_features(target_sn, cutoffs)

    hist = hist.drop(columns=["cutoff_date"], errors="ignore")
    hist = hist.sort_values(["serial_number", "date"], kind="mergesort")
    hist = hist.groupby("serial_number", sort=False).tail(14)

    if hist.empty:
        return zero_features(target_sn, cutoffs)

    raw_nums = [i for i in RAW_ATTRS if f"smart_{i}_raw" in hist.columns]
    norm_nums = [i for i in NORM_ATTRS if f"smart_{i}_normalized" in hist.columns]
    raw_cols = [f"smart_{i}_raw" for i in raw_nums]
    norm_cols = [f"smart_{i}_normalized" for i in norm_nums]
    base_cols = raw_cols + norm_cols

    if raw_cols:
        hist[raw_cols] = np.log1p(hist[raw_cols].clip(lower=0).astype("float32"))
    if norm_cols:
        hist[norm_cols] = hist[norm_cols].clip(lower=0).astype("float32")

    crit_nums = [i for i in CRITICAL_RAW if i in raw_nums]
    extra_cols = []
    if crit_nums:
        grp_for_shift = hist.groupby("serial_number", sort=False)
        for i in crit_nums:
            c = f"smart_{i}_raw"
            d3 = hist[c] - grp_for_shift[c].shift(3)
            d7 = hist[c] - grp_for_shift[c].shift(7)
            c3 = c + "_d3"
            c7 = c + "_d7"
            hist[c3] = d3.clip(lower=0).astype("float32")
            hist[c7] = d7.clip(lower=0).astype("float32")
            extra_cols.extend([c3, c7])

    grp = hist.groupby("serial_number", sort=False)

    date_agg = grp["date"].agg(["first", "last", "count"])
    date_agg.index = date_agg.index.astype("object")

    x = pd.DataFrame(index=date_agg.index)
    x["snap_count"] = date_agg["count"].astype("float32")
    x["window_span_days"] = (date_agg["last"] - date_agg["first"]).dt.days.astype("float32")

    cutoff_idx = pd.to_datetime(x.index.map(cutoff_map), errors="coerce")
    x["days_last_to_cutoff"] = (cutoff_idx - date_agg["last"]).dt.days.astype("float32")
    x["days_first_to_cutoff"] = (cutoff_idx - date_agg["first"]).dt.days.astype("float32")
    x["avg_gap_days"] = x["window_span_days"] / np.maximum(x["snap_count"] - 1.0, 1.0)
    x["snap_ratio"] = x["snap_count"] / 14.0

    if "capacity_bytes" in hist.columns:
        cap_last = grp["capacity_bytes"].agg("last")
        cap_last.index = cap_last.index.astype("object")
        cap_last = cap_last.reindex(x.index)
        x["capacity_log"] = np.log1p(cap_last.fillna(0).astype("float32").clip(lower=0))
    else:
        x["capacity_log"] = 0.0

    span_safe = np.maximum(x["window_span_days"].to_numpy(dtype="float32"), 1.0)

    if base_cols:
        agg = grp[base_cols].agg(["first", "last", "mean", "max", "min"])
        agg.index = agg.index.astype("object")
        agg = agg.reindex(x.index)

        last = agg.xs("last", axis=1, level=1)
        first = agg.xs("first", axis=1, level=1)
        mean = agg.xs("mean", axis=1, level=1)
        maxv = agg.xs("max", axis=1, level=1)
        minv = agg.xs("min", axis=1, level=1)

        for c in base_cols:
            lv = last[c]
            fv = first[c]
            mv = mean[c]
            xv = maxv[c]
            nv = minv[c]

            x[c + "_last"] = lv.astype("float32")
            delta = lv - fv

            if c in MONOTONIC_RAW_COLS:
                delta_np = np.maximum(delta.to_numpy(dtype="float32"), 0.0)
                x[c + "_delta"] = delta_np.astype("float32")
                x[c + "_reset"] = (delta < 0).astype("float32")
                x[c + "_delta_per_day"] = (delta_np / span_safe).astype("float32")
                x[c + "_nonzero"] = (lv > 0).astype("float32")
            elif c.endswith("_raw"):
                x[c + "_delta"] = delta.astype("float32")
                x[c + "_nonzero"] = (lv > 0).astype("float32")
            else:
                x[c + "_delta"] = delta.astype("float32")
                x[c + "_lt100"] = (lv < 100).astype("float32")
                x[c + "_lt90"] = (lv < 90).astype("float32")
                x[c + "_missing"] = lv.isna().astype("float32")

            x[c + "_range"] = (xv - nv).astype("float32")
            x[c + "_dev"] = (lv - mv).astype("float32")

        if crit_nums:
            for i in crit_nums:
                c = f"smart_{i}_raw"
                lv = last[c]
                fv = first[c]
                x[c + "_became"] = ((lv > 0) & (fv == 0)).astype("float32")
                x[c + "_missing"] = lv.isna().astype("float32")

    if extra_cols:
        extra_agg = grp[extra_cols].agg(["last", "max"])
        extra_agg.index = extra_agg.index.astype("object")
        extra_agg = extra_agg.reindex(x.index)

        last_e = extra_agg.xs("last", axis=1, level=1)
        max_e = extra_agg.xs("max", axis=1, level=1)

        for c in extra_cols:
            x[c + "_last"] = last_e[c].astype("float32")
            x[c + "_max"] = max_e[c].astype("float32")
            if c.endswith("_d3") or c.endswith("_d7"):
                x[c + "_per_day"] = (x[c + "_last"].to_numpy(dtype="float32") / span_safe).astype("float32")

    x = x.reindex(target_sn)

    for c in META_COLS:
        if c in x.columns:
            x[c] = x[c].fillna(0).astype("float32")

    for c in x.columns:
        if c.endswith("_missing"):
            x[c] = x[c].fillna(1.0).astype("float32")

    add_vendor_from_cutoffs(x, cutoffs)
    return x.astype("float32")


def make_model(num_leaves=31, min_child_samples=30, learning_rate=0.035, n_estimators=300):
    return lgb.LGBMClassifier(
        objective="binary",
        n_estimators=n_estimators,
        learning_rate=learning_rate,
        num_leaves=num_leaves,
        max_depth=-1,
        min_child_samples=min_child_samples,
        min_child_weight=1e-3,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.7,
        reg_lambda=1.0,
        reg_alpha=0.1,
        max_bin=63,
        verbose=-1,
        n_jobs=-1,
        random_state=0,
    )


def fit_predict(x, y, w, xq):
    x = np.asarray(x, dtype="float32")
    xq = np.asarray(xq, dtype="float32")
    y = np.asarray(y, dtype="int32")
    w = np.asarray(w, dtype="float64")

    if x.shape[0] == 0:
        return np.zeros(0, dtype="float32"), np.zeros(xq.shape[0], dtype="float32")

    if x.shape[0] < 3 or int(y.sum()) < 3 or int((1 - y).sum()) < 3:
        model = make_model()
        model.fit(x, y, sample_weight=w)
        oof = model.predict_proba(x)[:, 1].astype("float32")
        if xq.shape[0] == 0:
            scores = np.zeros(0, dtype="float32")
        else:
            scores = model.predict_proba(xq)[:, 1].astype("float32")
        return oof, scores

    skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=0)
    oof = np.zeros(x.shape[0], dtype="float64")
    scores = np.zeros(xq.shape[0], dtype="float64")
    n_models = 0

    for train_idx, val_idx in skf.split(x, y):
        for cfg in CONFIGS:
            model = make_model(
                num_leaves=cfg["num_leaves"],
                min_child_samples=cfg["min_child_samples"],
                learning_rate=cfg["learning_rate"],
                n_estimators=cfg["n_estimators"],
            )
            sw = w[train_idx]
            boost = float(cfg.get("pos_boost", 1.0))
            if boost != 1.0:
                sw = sw * np.where(y[train_idx] == 1, boost, 1.0)
            model.fit(x[train_idx], y[train_idx], sample_weight=sw)
            oof[val_idx] += model.predict_proba(x[val_idx])[:, 1]
            if xq.shape[0] > 0:
                scores += model.predict_proba(xq)[:, 1]
            n_models += 1

    oof /= float(len(CONFIGS))
    if scores.shape[0] > 0 and n_models > 0:
        scores /= float(n_models)

    return oof.astype("float32"), scores.astype("float32")


def choose_threshold(scores, y, w):
    scores = np.asarray(scores, dtype="float64")
    y = np.asarray(y, dtype="float64")
    w = np.asarray(w, dtype="float64")

    n = min(scores.size, y.size, w.size)
    if n == 0:
        return np.inf
    scores = scores[:n]
    y = y[:n]
    w = w[:n]

    scores = np.nan_to_num(scores, nan=0.0, posinf=1.0, neginf=0.0)
    y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
    w = np.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0)
    y = np.where(y > 0, 1.0, 0.0)
    w = np.where(w > 0, w, 0.0)

    total_pos = float(np.sum(w * y))
    total_neg = float(np.sum(w * (1.0 - y)))
    if total_pos <= 0:
        return np.inf

    order = np.argsort(-scores, kind="mergesort")
    s = scores[order]
    yy = y[order]
    ww = w[order]

    pos_w = ww * yy
    neg_w = ww * (1.0 - yy)

    cum_pos = np.cumsum(pos_w)
    cum_neg = np.cumsum(neg_w)
    cum_pos2 = np.cumsum(pos_w * pos_w)
    cum_neg2 = np.cumsum(neg_w * neg_w)

    total_pos2 = float(cum_pos2[-1]) if cum_pos2.size else 0.0
    N = float(s.size)

    change = np.empty(s.size, dtype=bool)
    change[0] = True
    if s.size > 1:
        change[1:] = s[1:] != s[:-1]

    starts = np.flatnonzero(change)
    if starts.size == 0:
        return np.inf

    ends = np.r_[starts[1:] - 1, s.size - 1]
    thresh = s[starts]

    tp = np.maximum(cum_pos[ends], 0.0)
    fp = np.maximum(cum_neg[ends], 0.0)
    fn = np.maximum(total_pos - tp, 0.0)

    D = tp + fp + fn
    f1 = np.zeros(tp.size, dtype="float64")
    valid = (D > 0) & (tp > 0)
    f1[valid] = 2.0 * tp[valid] / D[valid]

    g_tp = np.zeros(tp.size, dtype="float64")
    g_fp = np.zeros(tp.size, dtype="float64")
    valid2 = D > 0
    Dv = D[valid2]
    Dv2 = Dv * Dv
    g_tp[valid2] = 2.0 * (fp[valid2] + fn[valid2]) / Dv2
    g_fp[valid2] = -2.0 * tp[valid2] / Dv2
    g_fn = g_fp

    tp2 = cum_pos2[ends]
    fp2 = cum_neg2[ends]
    fn2 = np.maximum(total_pos2 - tp2, 0.0)

    var_tp = np.maximum(tp2 - (tp * tp) / N, 0.0)
    var_fp = np.maximum(fp2 - (fp * fp) / N, 0.0)
    var_fn = np.maximum(fn2 - (fn * fn) / N, 0.0)

    cov_tp_fp = -(tp * fp) / N
    cov_tp_fn = -(tp * fn) / N
    cov_fp_fn = -(fp * fn) / N

    var_f1 = (
        g_tp * g_tp * var_tp
        + g_fp * g_fp * var_fp
        + g_fn * g_fn * var_fn
        + 2.0 * g_tp * g_fp * cov_tp_fp
        + 2.0 * g_tp * g_fn * cov_tp_fn
        + 2.0 * g_fp * g_fn * cov_fp_fn
    )
    var_f1 = np.maximum(var_f1, 0.0)

    lower = f1 - 1.2815517 * np.sqrt(var_f1)
    lower = np.where(np.isfinite(lower), lower, -1.0)

    far = np.zeros(tp.size, dtype="float64")
    if total_neg > 0:
        far = fp / total_neg

    obj = lower + 1e-6 * f1
    obj = np.where(far <= 0.01, obj, obj - 0.05 * (far - 0.01))

    best = int(np.argmax(obj))
    return float(thresh[best])


def write_output(serials, scores, alarm, out_path):
    out = pd.DataFrame(
        {
            "serial_number": serials,
            "score": scores,
            "alarm": alarm,
        }
    )
    out.to_csv(out_path, index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--split", required=True, choices=["val", "test"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    data_dir = args.data_dir
    q_idx = pd.read_csv(
        os.path.join(data_dir, f"{args.split}_index.csv"),
        parse_dates=["cutoff_date"],
    )

    if len(q_idx) == 0:
        write_output(
            np.array([], dtype="object"),
            np.array([], dtype="float64"),
            np.array([], dtype="int64"),
            args.out,
        )
        return

    train_lab = pd.read_csv(
        os.path.join(data_dir, "train_labels.csv"),
        parse_dates=["cutoff_date"],
    )

    if "serial_number" in train_lab.columns:
        lab = train_lab.drop_duplicates(subset=["serial_number"], keep="last").reset_index(drop=True)
    else:
        lab = pd.DataFrame()

    del train_lab

    if len(lab) == 0 or "serial_number" not in lab.columns:
        q_serials = q_idx["serial_number"].astype("object")
        scores = np.zeros(len(q_serials), dtype="float64")
        alarm = np.zeros(len(q_serials), dtype="int64")
        write_output(q_serials, scores, alarm, args.out)
        return

    serials = lab["serial_number"].astype("object")

    if "label" in lab.columns:
        y = lab["label"].to_numpy(dtype="float64")
    else:
        y = np.zeros(len(lab), dtype="float64")
    y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
    y = np.where(y > 0, 1.0, 0.0).astype("int32")

    if "weight" in lab.columns:
        w = lab["weight"].to_numpy(dtype="float64")
    else:
        w = np.ones(len(lab), dtype="float64")
    w = np.nan_to_num(w, nan=1.0, posinf=1.0, neginf=1.0)
    w = np.where(w > 0, w, 1.0)

    if int(y.sum()) == 0:
        q_serials = q_idx["serial_number"].astype("object")
        scores = np.zeros(len(q_serials), dtype="float64")
        alarm = np.zeros(len(q_serials), dtype="int64")
        write_output(q_serials, scores, alarm, args.out)
        return

    q_hist = read_history(os.path.join(data_dir, f"{args.split}_history.csv.gz"))
    x_q = build_features(q_hist, q_idx)
    del q_hist

    train_hist = read_history(os.path.join(data_dir, "train_history.csv.gz"))
    x_tr = build_features(train_hist, lab)
    del train_hist

    x_tr = x_tr.reindex(serials)
    cols = list(x_tr.columns)

    q_serials = q_idx["serial_number"].astype("object")
    x_q = x_q.reindex(q_serials)

    if len(cols) == 0 or len(x_tr) == 0:
        scores = np.zeros(len(x_q), dtype="float64")
        alarm = np.zeros(len(x_q), dtype="int64")
        write_output(q_serials, scores, alarm, args.out)
        return

    x_tr = x_tr.reindex(columns=cols, fill_value=np.nan).astype("float32")
    x_q = x_q.reindex(columns=cols, fill_value=np.nan)

    miss_cols = [c for c in cols if c.endswith("_missing")]
    if miss_cols:
        x_tr[miss_cols] = x_tr[miss_cols].fillna(1.0).astype("float32")
        x_q[miss_cols] = x_q[miss_cols].fillna(1.0).astype("float32")
    x_q = x_q.astype("float32")

    oof, scores = fit_predict(x_tr, y, w, x_q)

    scores = np.asarray(scores, dtype="float64")
    scores = np.nan_to_num(scores, nan=0.0, posinf=1.0, neginf=0.0)

    threshold = choose_threshold(oof, y, w)

    oof = np.asarray(oof, dtype="float64")
    oof = np.nan_to_num(oof, nan=0.0, posinf=1.0, neginf=0.0)

    if len(scores) > 0:
        if len(oof) > 0:
            oof_frac = float(np.mean(oof >= threshold))
        else:
            oof_frac = 0.0

        if oof_frac <= 0.0:
            threshold = float(np.max(scores) + 1.0)
        elif oof_frac >= 1.0:
            threshold = float(np.min(scores) - 1.0)
        else:
            direct_frac = float(np.mean(scores >= threshold))
            if direct_frac <= 0.0 or direct_frac > 4.0 * oof_frac or direct_frac < 0.25 * oof_frac:
                target_frac = oof_frac
                if 0.0 < target_frac < 1.0:
                    threshold = float(np.quantile(scores, 1.0 - target_frac))

    alarm = (scores >= threshold).astype("int64")

    write_output(q_serials, scores, alarm, args.out)


if __name__ == "__main__":
    main()