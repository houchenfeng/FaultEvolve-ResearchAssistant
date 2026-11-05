"""Standalone GPU candidate; only documented public inputs are opened.

Architecture settings are injected by the experiment controller. All calibration,
normalization and epoch selection use the training split only.
"""
import argparse
import copy
import os
import time

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import average_precision_score
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.preprocessing import QuantileTransformer
from torch import nn

CONFIG = {'family': 'tcn', 'width': 128, 'depth': 1, 'dropout': 0.1, 'lr': 0.0003, 'weight_decay': 0.001, 'batch_size': 1024, 'epochs': 60, 'positive_boost': 3.0, 'threshold_scale': 1.2, 'seed': 20261020, 'train_seconds': 240, 'normalization': 'quantile', 'folds': 3, 'feature_set': 'trends', 'focal_gamma': 0.0, 'model_identity': False, 'smart_subset': 'all', 'epoch_objective': 'auprc', 'replicas': 3, 'ranking_weight': 0.0, 'device_context': True, 'tree_blend': 0.5}


def device_context(history, index, frame, columns):
    """Transfer explicit metadata/reset features from the inspected ML implementation."""
    dates = history.assign(date=pd.to_datetime(history.date)).groupby("serial_number").date.agg(
        ["min", "max", "count"]).reindex(index.serial_number)
    cutoff = pd.to_datetime(index.cutoff_date).to_numpy()
    span = ((dates["max"] - dates["min"]) / pd.Timedelta(days=1)).to_numpy()
    latest_age = (cutoff - dates["max"].to_numpy()) / np.timedelta64(1, "D")
    count = dates["count"].to_numpy()
    capacity = np.zeros(len(index))
    if "capacity_bytes" in history:
        capacity = history.groupby("serial_number").capacity_bytes.last().reindex(
            index.serial_number).to_numpy(dtype=np.float64)
        capacity = np.log1p(np.maximum(capacity, 0))
    metadata = np.column_stack([count / 14, span / 14, latest_age / 14,
                                span / np.maximum(count - 1, 1), capacity])
    counters = {4, 5, 9, 10, 12, 187, 188, 191, 192, 193, 196, 197, 198, 199, 241, 242}
    monotonic = [c for c in columns if c.endswith("_raw") and int(c.split("_")[1]) in counters]
    grouped = frame.groupby("serial_number")
    delta = (grouped[monotonic].last() - grouped[monotonic].first()).reindex(
        index.serial_number).to_numpy()
    # Counter decreases are reset indicators, not negative degradation speed.
    physical = np.concatenate([np.maximum(delta, 0) / np.maximum(span[:, None], 1),
                               (delta < 0).astype(np.float32)], axis=1)
    return np.nan_to_num(np.concatenate([metadata, physical], axis=1),
                         nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)


def features(history, index, columns):
    history = history.sort_values(["serial_number", "date"])
    raw = history[columns].to_numpy(dtype=np.float32, copy=True)
    raw[~np.isfinite(raw)] = np.nan
    # Signed log compresses counters without turning missing values into evidence.
    raw = np.sign(raw) * np.log1p(np.abs(raw))
    frame = pd.DataFrame(raw, columns=columns, index=history.index)
    frame["serial_number"] = history["serial_number"]
    grouped = frame.groupby("serial_number", sort=False)
    parts = [grouped.last(), grouped.mean(), grouped.std(), grouped.max(),
             grouped.last() - grouped.first(), grouped.count() / 14.0]
    if CONFIG.get("feature_set", "basic") == "trends":
        critical = [c for c in columns if c in [
            "smart_5_raw", "smart_187_raw", "smart_188_raw",
            "smart_197_raw", "smart_198_raw", "smart_199_raw"]]
        # Domain priors from the historical ML program: critical-counter growth
        # and occurrence are hypotheses to test, not automatically valid findings.
        for lag in [3, 7]:
            delta = frame[critical] - grouped[critical].shift(lag)
            delta["serial_number"] = frame.serial_number
            parts.append(delta.groupby("serial_number").last())
        occurrence = (frame[critical] > 0).astype(np.float32)
        occurrence["serial_number"] = frame.serial_number
        parts.append(occurrence.groupby("serial_number").mean())
    tab = np.concatenate([p.reindex(index.serial_number).to_numpy() for p in parts], axis=1)
    if CONFIG.get("device_context", False):
        tab = np.concatenate([tab, device_context(history, index, frame, columns)], axis=1)
    model = index.model.fillna("").astype(str)
    vendors = np.column_stack([model.str.startswith(v).to_numpy()
                               for v in ["ST", "TOSHIBA", "HGST", "WDC"]])
    tab = np.concatenate([tab, vendors], axis=1).astype(np.float32)
    # Align observations by calendar day, preserving gaps instead of compressing time.
    lookup = pd.Index(index.serial_number)
    rows = lookup.get_indexer(history.serial_number)
    cutoff = pd.to_datetime(index.cutoff_date).to_numpy()
    dates = pd.to_datetime(history.date).to_numpy()
    valid = rows >= 0
    age = np.zeros(len(rows), dtype=np.int64)
    age[valid] = ((cutoff[rows[valid]] - dates[valid]) / np.timedelta64(1, "D")).astype(int)
    valid &= (age >= 0) & (age < 14)
    seq = np.zeros((len(index), len(columns) * 2, 14), dtype=np.float32)
    rr, tt = rows[valid], 13 - age[valid]
    seq[rr, :len(columns), tt] = np.nan_to_num(raw[valid], nan=0.0)
    seq[rr, len(columns):, tt] = np.isfinite(raw[valid])
    return np.nan_to_num(tab, nan=0.0, posinf=0.0, neginf=0.0), seq


class Network(nn.Module):
    def __init__(self, tab_dim, seq_dim, cfg):
        super().__init__()
        self.temporal = cfg["family"] in ["tcn", "dual"]
        self.recurrent = cfg["family"] in ["gru", "dual"]
        width = cfg["width"]
        if self.temporal:
            self.conv = nn.Sequential(
                nn.Conv1d(seq_dim, 32, 3, padding=1), nn.ReLU(),
                nn.Conv1d(32, 32, 3, padding=2, dilation=2), nn.ReLU())
            tab_dim += 64
        if self.recurrent:
            self.gru = nn.GRU(seq_dim, 32, batch_first=True)
            tab_dim += 64
        self.input = nn.Linear(tab_dim, width)
        self.blocks = nn.ModuleList([
            nn.Sequential(nn.LayerNorm(width), nn.Linear(width, width),
                          nn.ReLU(), nn.Dropout(cfg["dropout"]), nn.Linear(width, width))
            for _ in range(cfg["depth"])])
        self.output = nn.Linear(width, 1)

    def forward(self, tab, seq):
        if self.temporal:
            z = self.conv(seq)
            tab = torch.cat([tab, z.mean(dim=2), z[:, :, -1]], dim=1)
        if self.recurrent:
            z, _ = self.gru(seq.transpose(1, 2))
            tab = torch.cat([tab, z.mean(dim=1), z[:, -1]], dim=1)
        x = torch.relu(self.input(tab))
        for block in self.blocks:
            x = torch.relu(x + block(x))
        return self.output(x).flatten()


def threshold(y, p, w):
    order = np.argsort(-p)
    ys, ps, ws = y[order], p[order], w[order]
    tp = np.cumsum(ws * ys)
    fp = np.cumsum(ws * (1 - ys))
    f1 = 2 * tp / np.maximum(tp + fp + np.sum(w * y), 1e-12)
    # Only ends of tied-score groups are realizable threshold decisions.
    ends = np.r_[ps[:-1] != ps[1:], True]
    f1[~ends] = -1
    return float(ps[np.argmax(f1)])


def operational_proxy(y, p, w, auprc):
    order = np.argsort(-p, kind="stable")
    ys, ps, ws = y[order], p[order], w[order]
    tp, fp = np.cumsum(ws * ys), np.cumsum(ws * (1 - ys))
    positive, negative = np.sum(w * y), np.sum(w * (1 - y))
    ends = np.r_[ps[:-1] != ps[1:], True]
    f1 = 2 * tp / np.maximum(tp + fp + positive, 1e-12)
    allowed = ends & (fp / max(negative, 1e-12) <= 0.002)
    recall = np.max(tp[allowed] / max(positive, 1e-12)) if allowed.any() else 0.0
    # Training-only model selection proxy, without the external bootstrap estimator.
    return 0.5 * float(np.max(f1[ends])) + 0.3 * auprc + 0.2 * recall


def hard_negative_ranking(logits, labels, weights):
    """Training-batch hypothesis: separate positives from the 16 highest-scoring negatives."""
    positive, negative = labels > 0, labels <= 0
    if not positive.any() or not negative.any():
        return logits.sum() * 0
    negative_logits = logits[negative]
    ids = torch.topk(negative_logits, min(16, negative_logits.numel())).indices
    differences = negative_logits[ids][None, :] - logits[positive][:, None]
    pair_weights = weights[positive][:, None] * weights[negative][ids][None, :]
    return (nn.functional.softplus(differences) * pair_weights).sum() / pair_weights.sum().clamp_min(1e-12)


def fit_one(tab, seq, y, w, query_tab, query_seq, cfg, train, valid):
    torch.set_num_threads(4)
    torch.manual_seed(cfg["seed"])
    np.random.seed(cfg["seed"])
    if not torch.cuda.is_available():
        raise RuntimeError("GPU is required for this candidate")
    device = torch.device("cuda")
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    if cfg.get("normalization", "standard") == "quantile":
        transformer = QuantileTransformer(n_quantiles=min(256, len(train)),
                                         output_distribution="normal", random_state=cfg["seed"])
        transformer.fit(tab[train])
        tab, query_tab = transformer.transform(tab), transformer.transform(query_tab)
    else:
        mean, std = tab[train].mean(0), tab[train].std(0)
        std = np.maximum(std, 0.05)
        tab = np.clip((tab - mean) / std, -10, 10)
        query_tab = np.clip((query_tab - mean) / std, -10, 10)
    # Sequence statistics are fitted only on inner training entities.
    scale = np.maximum(np.abs(seq[train]).max(axis=(0, 2)), 1.0)
    seq, query_seq = seq / scale[None, :, None], query_seq / scale[None, :, None]
    x, s, yy, ww = [torch.as_tensor(a, dtype=torch.float32, device=device)
                    for a in [tab, seq, y, w / w.mean()]]
    qx, qs = [torch.as_tensor(a, dtype=torch.float32, device=device)
              for a in [query_tab, query_seq]]
    model = Network(x.shape[1], s.shape[1], cfg).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["lr"],
                                 weight_decay=cfg["weight_decay"])
    pos = torch.tensor(cfg["positive_boost"], device=device)
    best_objective, best_state, best_p, stale = -1, None, None, 0
    start = time.monotonic()
    for epoch in range(cfg["epochs"]):
        model.train()
        order = np.random.permutation(train)
        for offset in range(0, len(order), cfg["batch_size"]):
            ids = order[offset:offset + cfg["batch_size"]]
            optimizer.zero_grad(set_to_none=True)
            logits = model(x[ids], s[ids])
            loss = nn.functional.binary_cross_entropy_with_logits(
                logits, yy[ids], pos_weight=pos, reduction="none")
            gamma = cfg.get("focal_gamma", 0.0)
            if gamma:
                probability = torch.sigmoid(logits)
                pt = torch.where(yy[ids] > 0, probability, 1 - probability)
                loss = loss * (1 - pt).pow(gamma)
            objective_loss = (loss * ww[ids]).mean()
            if cfg.get("ranking_weight", 0.0):
                objective_loss = objective_loss + cfg["ranking_weight"] * hard_negative_ranking(
                    logits, yy[ids], ww[ids])
            objective_loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
        model.eval()
        with torch.no_grad():
            p = torch.sigmoid(model(x[valid], s[valid])).cpu().numpy()
        ap = average_precision_score(y[valid], p, sample_weight=w[valid])
        objective = operational_proxy(y[valid], p, w[valid], ap) if cfg.get(
            "epoch_objective", "auprc") == "operational_proxy" else ap
        if objective > best_objective:
            best_objective, best_p, best_state, stale = objective, p, copy.deepcopy(model.state_dict()), 0
        else:
            stale += 1
        if stale >= 10 or time.monotonic() - start > cfg["train_seconds"]:
            break
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        scores = np.concatenate([torch.sigmoid(model(qx[i:i+2048], qs[i:i+2048])).cpu().numpy()
                                 for i in range(0, len(qx), 2048)])
    blend = cfg.get("tree_blend", 0.0)
    if blend:
        from lightgbm import LGBMClassifier
        if blend not in [0.25, 0.5]:
            raise ValueError("tree_blend must be 0, 0.25 or 0.5")
        # Same inner training entities; no validation/query labels enter the tree fit.
        tree = LGBMClassifier(n_estimators=150, num_leaves=15, min_child_samples=50,
                             learning_rate=0.05, n_jobs=4, verbosity=-1,
                             random_state=cfg["seed"], deterministic=True, force_col_wise=True)
        tree.fit(tab[train], y[train],
                 sample_weight=w[train] * np.where(y[train] > 0, cfg["positive_boost"], 1.0))
        scores = (1 - blend) * scores + blend * tree.predict_proba(query_tab)[:, 1]
        best_p = (1 - blend) * best_p + blend * tree.predict_proba(tab[valid])[:, 1]
    return scores, best_p


def fit_predict(tab, seq, y, w, query_tab, query_seq, cfg):
    folds = cfg.get("folds", 1)
    if folds == 1:
        splits = [train_test_split(np.arange(len(y)), test_size=0.2,
                                   random_state=cfg["seed"], stratify=y)]
    else:
        splits = list(StratifiedKFold(n_splits=folds, shuffle=True,
                                    random_state=cfg["seed"]).split(tab, y))
    query_predictions, validation_y, validation_p, validation_w = [], [], [], []
    replicas = cfg.get("replicas", 1)
    if replicas not in [1, 3]:
        raise ValueError("replicas must be 1 or 3")
    for number, (train, valid) in enumerate(splits):
        fold_predictions = []
        for replica in range(replicas):
            settings = {**cfg, "seed": cfg["seed"] + number + replica * 100003,
                        "train_seconds": cfg["train_seconds"] / (len(splits) * replicas)}
            scores, p = fit_one(tab, seq, y, w, query_tab, query_seq, settings, train, valid)
            query_predictions.append(scores)
            fold_predictions.append(p)
        validation_y.append(y[valid])
        # Calibrate the same ensemble operation on entities unseen by every replica.
        validation_p.append(np.mean(fold_predictions, axis=0))
        validation_w.append(w[valid])
    scores = np.mean(query_predictions, axis=0)
    # OOF calibration uses training labels only; query labels are never accessible.
    cut = threshold(np.concatenate(validation_y), np.concatenate(validation_p),
                    np.concatenate(validation_w)) * cfg["threshold_scale"]
    return scores, scores >= cut


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--split", required=True, choices=["val", "test"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    train = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv"))
    query = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))
    history = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"))
    future = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_history.csv.gz"))
    columns = sorted(c for c in history.columns if c.startswith("smart_"))
    if CONFIG.get("smart_subset") == "reliability":
        attributes = {5, 9, 187, 188, 194, 197, 198, 199}
        columns = [c for c in columns if int(c.split("_")[1]) in attributes]
    tab, seq = features(history, train, columns)
    qt, qs = features(future, query, columns)
    if CONFIG.get("model_identity", False):
        categories = sorted(train.model.dropna().unique())
        tab = np.concatenate([tab, (train.model.to_numpy()[:, None] == categories).astype(np.float32)], axis=1)
        qt = np.concatenate([qt, (query.model.to_numpy()[:, None] == categories).astype(np.float32)], axis=1)
    p, alarm = fit_predict(tab, seq, train.label.to_numpy(dtype=np.float32),
                          train.weight.to_numpy(dtype=np.float32), qt, qs, CONFIG)
    pd.DataFrame(dict(serial_number=query.serial_number, score=p,
                      alarm=alarm.astype(int))).to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
