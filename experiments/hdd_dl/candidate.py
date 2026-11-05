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

CONFIG = dict(family="mlp", width=128, depth=2, dropout=0.15, lr=0.001,
              weight_decay=0.001, batch_size=1024, epochs=40, positive_boost=5.0,
              seed=20261020, train_seconds=240, threshold_scale=1.0)


def blend_predictions(neural, tree, weight, mode="probability"):
    """Apply the same fixed fusion rule to inner calibration and query scores."""
    if mode == "probability":
        return (1 - weight) * neural + weight * tree
    if mode != "logit":
        raise ValueError("fusion_mode must be probability or logit")
    neural = np.clip(np.asarray(neural, dtype=np.float64), 1e-7, 1 - 1e-7)
    tree = np.clip(np.asarray(tree, dtype=np.float64), 1e-7, 1 - 1e-7)
    logits = (1 - weight) * (np.log(neural) - np.log1p(-neural))
    logits += weight * (np.log(tree) - np.log1p(-tree))
    return 1 / (1 + np.exp(-logits))


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
    original = raw.copy() if CONFIG.get("sequence_relative_change", False) else None
    # Signed log compresses counters without turning missing values into evidence.
    raw = np.sign(raw) * np.log1p(np.abs(raw))
    frame = pd.DataFrame(raw, columns=columns, index=history.index)
    frame["serial_number"] = history["serial_number"]
    grouped = frame.groupby("serial_number", sort=False)
    parts = [grouped.last(), grouped.mean(), grouped.std(), grouped.max(),
             grouped.last() - grouped.first(), grouped.count() / 14.0]
    if CONFIG.get("window_contrasts", False):
        parts.extend([grouped.max() - grouped.min(), grouped.last() - grouped.mean()])
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
    if CONFIG.get("tab_missing_indicators", False):
        tab = np.concatenate([tab, np.isfinite(tab).astype(np.float32)], axis=1)
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
    if CONFIG.get("sequence_deltas", False):
        seq = append_sequence_deltas(seq)
    if original is not None:
        calendar = np.full((len(index), len(columns), 14), np.nan, dtype=np.float32)
        calendar[rr, :, tt] = original[valid]
        seq = np.concatenate([seq, relative_change_sequence(calendar)], axis=1)
    return np.nan_to_num(tab, nan=0.0, posinf=0.0, neginf=0.0), seq


def relative_change_sequence(calendar):
    """Log changes in raw units from each channel's first observed window value."""
    observed = np.isfinite(calendar)
    first = observed.argmax(axis=2, keepdims=True)
    baseline = np.take_along_axis(calendar, first, axis=2).astype(np.float64)
    # Float64 subtraction avoids overflow for finite float32 extrema.
    change = calendar.astype(np.float64) - baseline
    change = np.where(observed & np.isfinite(baseline), change, 0.)
    return (np.sign(change) * np.log1p(np.abs(change))).astype(np.float32)


def append_sequence_deltas(seq):
    """Append signed log-value changes only across consecutive observed days."""
    count = seq.shape[1] // 2
    values, observed = seq[:, :count], seq[:, count:]
    valid = np.zeros_like(observed)
    valid[:, :, 1:] = observed[:, :, 1:] * observed[:, :, :-1]
    delta = np.zeros_like(values)
    delta[:, :, 1:] = (values[:, :, 1:] - values[:, :, :-1]) * valid[:, :, 1:]
    return np.concatenate([seq, delta, valid], axis=1)


class CausalConv(nn.Module):
    def __init__(self, inputs, outputs, dilation):
        super().__init__()
        self.padding = 2 * dilation
        self.conv = nn.Conv1d(inputs, outputs, 3, padding=self.padding, dilation=dilation)

    def forward(self, x):
        return self.conv(x)[:, :, :-self.padding]


class TemporalAttentionPool(nn.Module):
    """Learn temporal weights, starting at the ordinary temporal mean."""
    def __init__(self, channels):
        super().__init__()
        self.direction = nn.Parameter(torch.zeros(channels))

    def forward(self, z):
        logits = torch.einsum("bct,c->bt", z, self.direction)
        weights = torch.softmax(logits, dim=1)
        return (z * weights[:, None, :]).sum(dim=2)


class Network(nn.Module):
    def __init__(self, tab_dim, seq_dim, cfg):
        super().__init__()
        self.temporal = cfg["family"] in ["tcn", "dual"]
        self.recurrent = cfg["family"] in ["gru", "dual"]
        self.temporal_max_pool = cfg.get("temporal_max_pool", False)
        self.temporal_flatten = cfg.get("temporal_flatten", False)
        if self.temporal_flatten and (not self.temporal or self.temporal_max_pool
                                      or cfg.get("temporal_attention", False)):
            raise ValueError("temporal_flatten requires TCN without alternate pooling")
        if cfg.get("temporal_attention", False) and not self.temporal:
            raise ValueError("temporal_attention requires a temporal convolution branch")
        self.attention_pool = TemporalAttentionPool(32) if cfg.get("temporal_attention", False) else None
        width = cfg["width"]
        if self.temporal:
            context = cfg.get("temporal_context", "local")
            if context == "causal14":
                self.conv = nn.Sequential(CausalConv(seq_dim, 32, 1), nn.ReLU(),
                    CausalConv(32, 32, 2), nn.ReLU(), CausalConv(32, 32, 4), nn.ReLU())
            elif context in ("local", "symmetric14"):
                self.conv = nn.Sequential(
                    nn.Conv1d(seq_dim, 32, 3, padding=1), nn.ReLU(),
                    nn.Conv1d(32, 32, 3, padding=2, dilation=2), nn.ReLU())
                if context == "symmetric14":
                    self.conv.append(nn.Conv1d(32, 32, 3, padding=4, dilation=4))
                    self.conv.append(nn.ReLU())
            else:
                raise ValueError("Unknown temporal_context")
            tab_dim += 32 * 14 if self.temporal_flatten else (96 if self.temporal_max_pool else 64)
        if self.recurrent:
            self.gru = nn.GRU(seq_dim, 32, batch_first=True)
            tab_dim += 96 if self.temporal_max_pool else 64
        self.tabm_members = cfg.get("tabm_members", 0)
        if self.tabm_members not in (0, 8, 16):
            raise ValueError("tabm_members must be 0, 8 or 16")
        if self.tabm_members:
            if cfg.get("tree_residual", False):
                raise ValueError("TabM and tree_residual are separate experimental backends")
            from tabm import TabM
            embedding = cfg.get("tabm_embedding", "none")
            if embedding not in ("none", "periodic"):
                raise ValueError("tabm_embedding must be none or periodic")
            num_embeddings = None
            if embedding == "periodic":
                from rtdl_num_embeddings import PeriodicEmbeddings
                num_embeddings = PeriodicEmbeddings(tab_dim, d_embedding=16,
                    n_frequencies=16, frequency_init_scale=0.01, lite=True)
            self.tabm = TabM.make(n_num_features=tab_dim, d_out=1, k=self.tabm_members,
                                  num_embeddings=num_embeddings,
                                  n_blocks=cfg["depth"], d_block=width, dropout=cfg["dropout"])
            return
        self.input = nn.Linear(tab_dim, width)
        self.blocks = nn.ModuleList([
            nn.Sequential(nn.LayerNorm(width), nn.Linear(width, width),
                          nn.ReLU(), nn.Dropout(cfg["dropout"]), nn.Linear(width, width))
            for _ in range(cfg["depth"])])
        self.output = nn.Linear(width, 1)

    def forward(self, tab, seq):
        if self.temporal:
            z = self.conv(seq)
            if self.temporal_flatten:
                if z.shape[2] != 14:
                    raise ValueError("temporal_flatten requires a 14-day window")
                tab = torch.cat([tab, z.flatten(start_dim=1)], dim=1)
            else:
                pooled = self.attention_pool(z) if self.attention_pool is not None else z.mean(dim=2)
                tab = torch.cat([tab, pooled, z[:, :, -1]], dim=1)
                if self.temporal_max_pool:
                    tab = torch.cat([tab, z.max(dim=2).values], dim=1)
        if self.recurrent:
            z, _ = self.gru(seq.transpose(1, 2))
            tab = torch.cat([tab, z.mean(dim=1), z[:, -1]], dim=1)
            if self.temporal_max_pool:
                tab = torch.cat([tab, z.max(dim=1).values], dim=1)
        if self.tabm_members:
            return self.tabm(tab).squeeze(-1)
        x = torch.relu(self.input(tab))
        for block in self.blocks:
            x = torch.relu(x + block(x))
        return self.output(x).flatten()


def prediction_probability(logits):
    probabilities = torch.sigmoid(logits)
    return probabilities.mean(dim=1) if logits.ndim == 2 else probabilities


class WeightedTailRisk(nn.Module):
    """Experimental weighted CVaR surrogate, not an exact LibAUC reproduction.

    Each positive example owns a persistent auxiliary threshold. Model gradients
    use its pre-update value; threshold SGD uses detached weighted tail mass.
    Instantiate separately for every inner-training model.
    """
    def __init__(self, size, beta=0.002, step_size=0.001):
        super().__init__()
        if size < 1 or not np.isfinite(beta) or not 0 < beta <= 1:
            raise ValueError("Invalid tail-risk size or beta")
        if not np.isfinite(step_size) or step_size <= 0:
            raise ValueError("Invalid tail-risk step size")
        self.beta, self.step_size = beta, step_size
        self.register_buffer("thresholds", torch.full((size,), float(np.log(2))))

    @torch.no_grad()
    def refresh(self, logits, labels, weights):
        """Recompute empirical weighted tail thresholds on local training rows only."""
        if logits.ndim != 1 or not (logits.shape == labels.shape == weights.shape == self.thresholds.shape):
            raise ValueError("Refresh requires all local training rows in state order")
        if (not torch.isfinite(logits).all() or not torch.isfinite(weights).all()
                or (weights < 0).any() or not ((labels == 0) | (labels == 1)).all()):
            raise ValueError("Invalid refresh data")
        positive, negative = (labels == 1) & (weights > 0), (labels == 0) & (weights > 0)
        if not positive.any() or not negative.any():
            raise ValueError("Refresh needs positive and negative training weight")
        zn, wn = logits[negative], weights[negative].double()
        order = torch.argsort(zn, descending=True)
        cumulative = torch.cumsum(wn[order], dim=0)
        target = self.beta * cumulative[-1]
        index = torch.searchsorted(cumulative, target).clamp_max(len(order) - 1)
        boundary = zn[order[index]]
        self.thresholds[positive] = nn.functional.softplus(boundary - logits[positive])

    def forward(self, logits, labels, weights, indices, update=True):
        if logits.ndim != 1 or not (logits.shape == labels.shape == weights.shape == indices.shape):
            raise ValueError("Tail-risk inputs must be aligned vectors")
        if indices.dtype != torch.long or len(torch.unique(indices)) != len(indices):
            raise ValueError("Tail-risk indices must be unique integer sample IDs")
        if len(indices) and (indices.min() < 0 or indices.max() >= len(self.thresholds)):
            raise ValueError("Tail-risk sample ID outside training state")
        if (not torch.isfinite(logits).all() or not torch.isfinite(weights).all()
                or (weights < 0).any() or not ((labels == 0) | (labels == 1)).all()):
            raise ValueError("Invalid tail-risk logits, weights or labels")
        positive, negative = (labels == 1) & (weights > 0), (labels == 0) & (weights > 0)
        if not positive.any() or not negative.any():
            return logits.sum() * 0
        wp = weights[positive] / weights[positive].sum()
        wn = weights[negative] / weights[negative].sum()
        losses = nn.functional.softplus(logits[negative][None, :] - logits[positive][:, None])
        ids = indices[positive]
        thresholds = self.thresholds[ids].detach().clone()
        excess = losses - thresholds[:, None]
        risk = thresholds + (excess.clamp_min(0) * wn).sum(dim=1) / self.beta
        result = (wp * risk).sum()
        if update:
            with torch.no_grad():
                tail_mass = ((excess.detach() > 0) * wn).sum(dim=1)
                self.thresholds[ids] = (thresholds - self.step_size *
                    (1 - tail_mass / self.beta)).clamp_min(0)
        return result


@torch.no_grad()
def tail_mass_diagnostics(logits, labels, weights, thresholds, beta):
    """Aggregate empirical tail mass for the final model and its final state."""
    positive, negative = (labels == 1) & (weights > 0), (labels == 0) & (weights > 0)
    wp, wn = weights[positive].double(), weights[negative].double()
    wp, wn = wp / wp.sum(), wn / wn.sum()
    zp, zn, state = logits[positive].double(), logits[negative].double(), thresholds[positive].double()
    strict, inclusive = [], []
    for start in range(0, len(zp), 64):
        loss = nn.functional.softplus(zn[None, :] - zp[start:start+64, None])
        boundary = state[start:start+64, None]
        strict.append(((loss > boundary) * wn).sum(1))
        inclusive.append(((loss >= boundary) * wn).sum(1))
    strict, inclusive = torch.cat(strict), torch.cat(inclusive)
    return {"scope": "final_training_model_and_final_auxiliary_state",
        "weighted_mean_mass": float((strict * wp).sum()),
        "median_mass": float(strict.median()), "max_mass": float(strict.max()),
        "weighted_absolute_beta_gap": float(((strict - beta).abs() * wp).sum()),
        "weighted_stationary_interval_fraction": float(((strict <= beta) & (inclusive >= beta)).double().dot(wp)),
        "negative_effective_sample_count": float(1 / wn.square().sum()),
        "beta": beta}


def training_loss(logits, labels, weights, pos, gamma=0.0, ranking_weight=0.0, ranking_negatives=16):
    target = labels[:, None].expand_as(logits) if logits.ndim == 2 else labels
    sample_weights = weights[:, None] if logits.ndim == 2 else weights
    loss = nn.functional.binary_cross_entropy_with_logits(
        logits, target, pos_weight=pos, reduction="none")
    if gamma:
        if 0 < gamma < 1:
            # Avoid the infinite derivative of x**gamma at rounded x=0.
            signed_logits = torch.where(target > 0, logits, -logits)
            loss = loss * torch.exp(-gamma * nn.functional.softplus(signed_logits))
        else:
            probability = torch.sigmoid(logits)
            pt = torch.where(target > 0, probability, 1 - probability)
            loss = loss * (1 - pt).pow(gamma)
    result = (loss * sample_weights).mean()
    if ranking_weight:
        ranking = torch.stack([hard_negative_ranking(logits[:, i], labels, weights, ranking_negatives)
                               for i in range(logits.shape[1])]).mean() if logits.ndim == 2 else (
                                   hard_negative_ranking(logits, labels, weights, ranking_negatives))
        result = result + ranking_weight * ranking
    return result


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


def far_threshold_floor(y, p, w, budget):
    """Smallest realizable cut satisfying a weighted training-OOF FAR budget."""
    if not np.isfinite(budget) or not 0 <= budget <= 1:
        raise ValueError("alarm_far_budget must be between zero and one")
    order = np.argsort(-p, kind="stable")
    ps, ys, ws = p[order], y[order], w[order]
    negative = np.sum(w * (1 - y))
    if negative <= 0:
        raise ValueError("FAR calibration requires negative training examples")
    fp = np.cumsum(ws * (1 - ys))
    ends = np.r_[ps[:-1] != ps[1:], True]
    allowed = ends & (fp / negative <= budget)
    return float(ps[np.flatnonzero(allowed)[-1]]) if allowed.any() else float(
        np.nextafter(float(ps[0]), np.inf))


def calibration_threshold(y, p, w, cfg):
    """Estimate the alarm cut using only training OOF predictions and labels."""
    mode = cfg.get("threshold_estimator", "empirical")
    if mode == "empirical":
        return threshold(y, p, w)
    if mode == "near_optimal_median":
        order = np.argsort(-p, kind="stable")
        ys, ps, ws = y[order], p[order], w[order]
        tp, fp = np.cumsum(ws * ys), np.cumsum(ws * (1 - ys))
        f1 = 2 * tp / np.maximum(tp + fp + np.sum(w * y), 1e-12)
        ends = np.r_[ps[:-1] != ps[1:], True]
        eligible = np.flatnonzero(ends & (f1 >= .99 * np.max(f1[ends])))
        # Choose an observed tied-score endpoint, not an interpolated threshold.
        return float(ps[eligible[len(eligible) // 2]])
    if mode != "bootstrap_median":
        raise ValueError("Unknown threshold estimator")
    positive, negative = np.flatnonzero(y > 0), np.flatnonzero(y <= 0)
    if not len(positive) or not len(negative):
        return threshold(y, p, w)
    # Local RNG cannot change subsequent model initialization or minibatch order.
    rng = np.random.default_rng(cfg["seed"] + 7919)
    cuts = []
    for _ in range(31):
        ids = np.concatenate([rng.choice(positive, len(positive), replace=True),
                              rng.choice(negative, len(negative), replace=True)])
        cuts.append(threshold(y[ids], p[ids], w[ids]))
    return float(np.median(cuts))


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


def hard_negative_ranking(logits, labels, weights, negative_count=16):
    """Batch-tail hypothesis; the selected count is not a population FAR estimate."""
    if isinstance(negative_count, bool) or not isinstance(negative_count, int) or negative_count < 1:
        raise ValueError("ranking_negatives must be a positive integer")
    positive, negative = labels > 0, labels <= 0
    if not positive.any() or not negative.any():
        return logits.sum() * 0
    negative_logits = logits[negative]
    ids = torch.topk(negative_logits, min(negative_count, negative_logits.numel())).indices
    differences = negative_logits[ids][None, :] - logits[positive][:, None]
    pair_weights = weights[positive][:, None] * weights[negative][ids][None, :]
    return (nn.functional.softplus(differences) * pair_weights).sum() / pair_weights.sum().clamp_min(1e-12)


@torch.no_grad()
def update_average(average, model, decay):
    for target, source in zip(average.parameters(), model.parameters()):
        target.mul_(decay).add_(source, alpha=1 - decay)
    for target, source in zip(average.buffers(), model.buffers()):
        target.copy_(source)


def normalize_sequences(seq, query_seq, train, mode="maxabs"):
    """Fit channel scales on inner training entities; preserve missingness masks."""
    observed = np.abs(seq[train])
    if mode == "maxabs":
        scale = observed.max(axis=(0, 2))
    elif mode == "percentile99":
        scale = np.quantile(observed, 0.99, axis=(0, 2)).astype(seq.dtype)
    else:
        raise ValueError("sequence_normalization must be maxabs or percentile99")
    scale = np.maximum(scale, 1.0)[None, :, None]
    return seq / scale, query_seq / scale


def fit_tree_branch(tree_tab, y, w, cfg, train):
    blend = cfg.get("tree_blend", 0.0)
    from lightgbm import LGBMClassifier
    if blend not in [0.25, 0.5]:
        raise ValueError("tree_blend must be 0, 0.25 or 0.5")
    # Same inner training entities; no validation/query labels enter the tree fit.
    tree_rounds = cfg.get("tree_rounds", 150)
    if tree_rounds not in (150, 300):
        raise ValueError("tree_rounds must be 150 or 300")
    tree_leaves = cfg.get("tree_leaves", 15)
    if tree_leaves not in (15, 31):
        raise ValueError("tree_leaves must be 15 or 31")
    tree = LGBMClassifier(n_estimators=tree_rounds, num_leaves=tree_leaves, min_child_samples=50,
                         learning_rate=0.05, n_jobs=4, verbosity=-1,
                         random_state=cfg["seed"], deterministic=True, force_col_wise=True)
    tree_boost = cfg.get("tree_positive_boost", cfg["positive_boost"])
    if not np.isfinite(tree_boost) or tree_boost <= 0:
        raise ValueError("tree_positive_boost must be finite and positive")
    tree.fit(tree_tab[train], y[train],
             sample_weight=w[train] * np.where(y[train] > 0, tree_boost, 1.0))
    return tree


def crossfit_tree_prior(tab, query, y, w, cfg, train):
    """OOF priors for neural training; average equally sized trees elsewhere."""
    train = np.asarray(train)
    outside = np.setdiff1d(np.arange(len(tab)), train)
    prior = np.zeros(len(tab), dtype=np.float64)
    query_prior = np.zeros(len(query), dtype=np.float64)
    splits = StratifiedKFold(n_splits=3, shuffle=True, random_state=cfg["seed"])
    for fit, held in splits.split(tab[train], y[train]):
        tree = fit_tree_branch(tab, y, w, cfg, train[fit])
        prior[train[held]] = tree.predict_proba(tab[train[held]])[:, 1]
        if len(outside):
            prior[outside] += tree.predict_proba(tab[outside])[:, 1] / 3
        query_prior += tree.predict_proba(query)[:, 1] / 3
    return prior, query_prior


def prepare_fold_inputs(tab, seq, query_tab, query_seq, cfg, train):
    if cfg.get("normalization", "standard") == "quantile":
        transformer = QuantileTransformer(n_quantiles=min(256, len(train)),
                                         output_distribution="normal", random_state=cfg["seed"],
                                         subsample=cfg.get("quantile_subsample", 10000))
        transformer.fit(tab[train])
        tab, query_tab = transformer.transform(tab), transformer.transform(query_tab)
    else:
        mean, std = tab[train].mean(0), tab[train].std(0)
        std = np.maximum(std, 0.05)
        tab = np.clip((tab - mean) / std, -10, 10)
        query_tab = np.clip((query_tab - mean) / std, -10, 10)
    # Sequence statistics are fitted only on inner training entities.
    seq, query_seq = normalize_sequences(seq, query_seq, train,
                                        cfg.get("sequence_normalization", "maxabs"))
    return tab, seq, query_tab, query_seq


def fit_one(tab, seq, y, w, query_tab, query_seq, cfg, train, valid, diagnostics=None, prepared=None, shared_tree=None):
    patience = cfg.get("early_stop_patience", 10)
    if isinstance(patience, bool) or not isinstance(patience, int) or patience < 1:
        raise ValueError("early_stop_patience must be a positive integer")
    schedule = cfg.get("lr_schedule", "constant")
    if schedule not in ("constant", "plateau"):
        raise ValueError("lr_schedule must be constant or plateau")
    torch.set_num_threads(4)
    torch.manual_seed(cfg["seed"])
    np.random.seed(cfg["seed"])
    if not torch.cuda.is_available():
        raise RuntimeError("GPU is required for this candidate")
    device = torch.device("cuda")
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    tree_input = cfg.get("tree_input", "normalized")
    if tree_input not in ("normalized", "original"):
        raise ValueError("tree_input must be normalized or original")
    tree_tab, tree_query = tab, query_tab
    tab, seq, query_tab, query_seq = prepared if prepared is not None else prepare_fold_inputs(
        tab, seq, query_tab, query_seq, cfg, train)
    x, s, yy, ww = [torch.as_tensor(a, dtype=torch.float32, device=device)
                    for a in [tab, seq, y, w / w.mean()]]
    qx, qs = [torch.as_tensor(a, dtype=torch.float32, device=device)
              for a in [query_tab, query_seq]]
    model = Network(x.shape[1], s.shape[1], cfg).to(device)
    residual = cfg.get("tree_residual", False)
    if residual:
        if not cfg.get("tree_blend", 0.0) or cfg.get("hybrid_selection", False):
            raise ValueError("tree_residual requires a tree and standalone checkpoint selection")
        # Start at the tree's risk estimate, then learn a log-odds correction.
        nn.init.zeros_(model.output.weight)
        nn.init.zeros_(model.output.bias)
    decay = cfg.get("ema_decay", 0.0)
    if not 0 <= decay < 1:
        raise ValueError("ema_decay must be in [0, 1)")
    average = copy.deepcopy(model).requires_grad_(False) if decay else None
    if average is not None and average.recurrent:
        average.gru.flatten_parameters()
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["lr"],
                                 weight_decay=cfg["weight_decay"],
                                 **({"fused": True} if cfg.get("fused_optimizer", False) else {}))
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="max", factor=0.5, patience=3, threshold=0.0,
        threshold_mode="abs", min_lr=cfg["lr"] / 16) if schedule == "plateau" else None
    pos = torch.tensor(cfg["positive_boost"], device=device)
    tail_weight = cfg.get("tail_risk_weight", 0.0)
    if not np.isfinite(tail_weight) or tail_weight < 0:
        raise ValueError("tail_risk_weight must be finite and nonnegative")
    tail_risk, local_ids = None, None
    warmup = cfg.get("tail_warmup_epochs", 10)
    if tail_weight:
        if cfg.get("tabm_members", 0) or not isinstance(warmup, int) or warmup < 0:
            raise ValueError("Tail risk requires a scalar model and nonnegative warmup")
        tail_risk = WeightedTailRisk(len(train), cfg.get("tail_beta", 0.002),
                                     cfg.get("tail_step_size", 0.0001)).to(device)
        local_ids = torch.full((len(y),), -1, dtype=torch.long, device=device)
        local_ids[train] = torch.arange(len(train), device=device)
    tree, selection_tree_p = None, None
    prior, query_prior = None, None
    if residual or (cfg.get("hybrid_selection", False) and cfg.get("tree_blend", 0.0)):
        if tree_input == "normalized":
            tree_tab, tree_query = tab, query_tab
        crossfit = residual and cfg.get("residual_crossfit", False)
        if not crossfit:
            tree = fit_tree_branch(tree_tab, y, w, cfg, train)
        if residual:
            probabilities, query_probabilities = crossfit_tree_prior(
                tree_tab, tree_query, y, w, cfg, train) if crossfit else (
                    tree.predict_proba(tree_tab)[:, 1], tree.predict_proba(tree_query)[:, 1])
            def tree_logit(p):
                p = np.clip(p, 1e-7, 1 - 1e-7)
                return torch.as_tensor(np.log(p) - np.log1p(-p), dtype=torch.float32, device=device)
            prior, query_prior = tree_logit(probabilities), tree_logit(query_probabilities)
        else:
            selection_tree_p = tree.predict_proba(tree_tab[valid])[:, 1]
    best_objective, best_state, best_p, stale = -1, None, None, 0
    best_epoch, tail_batches, tail_loss_sum = -1, 0, 0.0
    start = time.monotonic()
    lr_history = []
    for epoch in range(cfg["epochs"]):
        if diagnostics is not None:
            lr_history.append(optimizer.param_groups[0]["lr"])
        if tail_risk is not None and cfg.get("tail_refresh", False) and epoch >= warmup:
            model.eval()
            with torch.no_grad():
                refresh_logits = torch.cat([model(x[t], s[t]) + (prior[t] if prior is not None else 0)
                    for t in (train[i:i+2048] for i in range(0, len(train), 2048))])
                tail_risk.refresh(refresh_logits, yy[train], ww[train])
        model.train()
        order = np.random.permutation(train)
        for offset in range(0, len(order), cfg["batch_size"]):
            ids = order[offset:offset + cfg["batch_size"]]
            optimizer.zero_grad(set_to_none=True)
            logits = model(x[ids], s[ids])
            if prior is not None:
                logits = logits + prior[ids]
            objective_loss = training_loss(logits, yy[ids], ww[ids], pos,
                                           cfg.get("focal_gamma", 0.0), cfg.get("ranking_weight", 0.0),
                                           cfg.get("ranking_negatives", 16))
            if tail_risk is not None and epoch >= warmup:
                tail_loss = tail_risk(
                    logits, yy[ids], ww[ids], local_ids[ids])
                objective_loss = objective_loss + tail_weight * tail_loss
                tail_batches += 1
                if diagnostics is not None:
                    tail_loss_sum += float(tail_loss.detach())
            objective_loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
            if average is not None:
                update_average(average, model, decay)
        evaluated = average if average is not None else model
        evaluated.eval()
        with torch.no_grad():
            logits = evaluated(x[valid], s[valid])
            if prior is not None:
                logits = logits + prior[valid]
            p = prediction_probability(logits).cpu().numpy()
        selection_p = p if selection_tree_p is None else blend_predictions(
            p, selection_tree_p, cfg["tree_blend"], cfg.get("fusion_mode", "probability"))
        ap = average_precision_score(y[valid], selection_p, sample_weight=w[valid])
        objective = operational_proxy(y[valid], selection_p, w[valid], ap) if cfg.get(
            "epoch_objective", "auprc") == "operational_proxy" else ap
        if objective > best_objective:
            best_objective, best_p, best_state, stale = objective, p, copy.deepcopy(evaluated.state_dict()), 0
            best_epoch = epoch
        else:
            stale += 1
        if scheduler is not None:
            scheduler.step(objective)
        if stale >= patience or time.monotonic() - start > cfg["train_seconds"]:
            break
    if diagnostics is not None:
        diagnostics.update(seed=cfg["seed"], epochs_completed=epoch + 1,
            learning_rates=lr_history,
            best_epoch=best_epoch, best_inner_objective=float(best_objective),
            tail_batches=tail_batches, selected_tail_stage=bool(tail_risk is not None and best_epoch >= warmup),
            mean_tail_loss=tail_loss_sum / max(tail_batches, 1))
        if tail_risk is not None:
            state = tail_risk.thresholds[torch.as_tensor(y[train] > 0, device=device)]
            diagnostics["positive_thresholds"] = {"min": float(state.min()),
                "median": float(state.median()), "max": float(state.max()),
                "zero_fraction": float((state == 0).float().mean())}
            model.eval()
            with torch.no_grad():
                train_logits = torch.cat([model(x[t], s[t]) + (prior[t] if prior is not None else 0)
                    for t in (train[i:i+2048] for i in range(0, len(train), 2048))])
                diagnostics["tail_mass"] = tail_mass_diagnostics(train_logits, yy[train],
                    ww[train], tail_risk.thresholds, tail_risk.beta)
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        scores = np.concatenate([prediction_probability(model(qx[i:i+2048], qs[i:i+2048]) +
                                 (query_prior[i:i+2048] if query_prior is not None else 0)).cpu().numpy()
                                 for i in range(0, len(qx), 2048)])
    blend = cfg.get("tree_blend", 0.0)
    if blend and not residual:
        if tree_input == "normalized":
            tree_tab, tree_query = tab, query_tab
        if shared_tree is None:
            if tree is None:
                tree = fit_tree_branch(tree_tab, y, w, cfg, train)
            tree_q, tree_v = tree.predict_proba(tree_query)[:, 1], tree.predict_proba(tree_tab[valid])[:, 1]
        else:
            tree_q, tree_v = shared_tree
        mode = cfg.get("fusion_mode", "probability")
        scores = blend_predictions(scores, tree_q, blend, mode)
        best_p = blend_predictions(best_p, tree_v, blend, mode)
    return scores, best_p


def select_alarm_threshold(y, p, w, cfg, diagnostics=None):
    base = calibration_threshold(y, p, w, cfg) * cfg["threshold_scale"]
    budget = cfg.get("alarm_far_budget")
    floor = far_threshold_floor(y, p, w, budget) if budget is not None else None
    cut = max(base, floor) if floor is not None else base
    if diagnostics is not None:
        negative = float(np.sum(w * (1 - y)))
        def rates(threshold_value):
            alarms = p >= threshold_value
            return {"far": float(np.sum(w * (1 - y) * alarms) / max(negative, 1e-12)),
                    "recall": float(np.sum(w * y * alarms) / max(float(np.sum(w * y)), 1e-12))}
        diagnostics.update(scope="training_oof_only", base_threshold=float(base),
                           floor_threshold=floor, final_threshold=float(cut), budget=budget,
                           floor_active=bool(floor is not None and floor > base),
                           changed_oof_alarms=int(np.count_nonzero((p >= base) != (p >= cut))),
                           base_rates=rates(base), final_rates=rates(cut),
                           entities=len(y), negative_weight=negative)
    return cut


def fit_predict(tab, seq, y, w, query_tab, query_seq, cfg, diagnostics=None):
    folds = cfg.get("folds", 1)
    partition = cfg.get("calibration_partition", "oof")
    if partition not in ("oof", "shared_calibration"):
        raise ValueError("Unknown calibration partition")
    if partition == "shared_calibration":
        if folds < 2 or cfg.get("fold_calibration", "raw") != "raw":
            raise ValueError("shared_calibration requires multiple folds and raw calibration")
        pool, calibration = train_test_split(np.arange(len(y)), test_size=0.1,
                                             random_state=cfg["seed"], stratify=y)
        splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=cfg["seed"])
        splits = [(pool[t], calibration) for t, _ in splitter.split(tab[pool], y[pool])]
    elif folds == 1:
        splits = [train_test_split(np.arange(len(y)), test_size=0.2,
                                   random_state=cfg["seed"], stratify=y)]
    else:
        splits = list(StratifiedKFold(n_splits=folds, shuffle=True,
                                    random_state=cfg["seed"]).split(tab, y))
    query_predictions, validation_y, validation_p, validation_w = [], [], [], []
    aligned_query = []
    replicas = cfg.get("replicas", 1)
    if replicas not in [1, 3, 9]:
        raise ValueError("replicas must be 1, 3 or 9")
    families = cfg.get("replica_families", [cfg["family"]] * replicas)
    if (not isinstance(families, (list, tuple)) or len(families) != replicas
            or any(f not in ("mlp", "tcn", "gru", "dual") for f in families)):
        raise ValueError("replica_families must contain one supported family per replica")
    share_tree = cfg.get("share_fold_tree", False)
    if share_tree and (not cfg.get("share_fold_preprocessing", False) or not cfg.get("tree_blend", 0)
                       or cfg.get("tree_residual", False) or cfg.get("hybrid_selection", False)):
        raise ValueError("Tree sharing requires shared preprocessing and standalone blended models")
    for number, (train, valid) in enumerate(splits):
        fold_predictions = []
        prepared = prepare_fold_inputs(tab, seq, query_tab, query_seq,
            {**cfg, "seed": cfg["seed"] + number}, train) if cfg.get("share_fold_preprocessing", False) else None
        shared_tree = None
        if share_tree:
            tree_tab, tree_query = (tab, query_tab) if cfg.get("tree_input", "normalized") == "original" else (prepared[0], prepared[2])
            tree = fit_tree_branch(tree_tab, y, w, {**cfg, "seed": cfg["seed"] + number}, train)
            shared_tree = (tree.predict_proba(tree_query)[:, 1], tree.predict_proba(tree_tab[valid])[:, 1])
            del tree
        for replica in range(replicas):
            settings = {**cfg, "seed": cfg["seed"] + number + replica * 100003,
                        "family": families[replica],
                        "train_seconds": cfg["train_seconds"] / (len(splits) * replicas)}
            details = {} if diagnostics is not None else None
            scores, p = fit_one(tab, seq, y, w, query_tab, query_seq, settings, train, valid,
                               **({"diagnostics": details} if details is not None else {}),
                               **({"prepared": prepared} if prepared is not None else {}),
                               **({"shared_tree": shared_tree} if shared_tree is not None else {}))
            if details is not None:
                details.update(fold=number, replica=replica)
                diagnostics.setdefault("models", []).append(details)
            query_predictions.append(scores)
            fold_predictions.append(p)
        validation_y.append(y[valid])
        # Replicas share held-out entities; ordinary OOF still differs across folds.
        fold_p = np.mean(fold_predictions, axis=0)
        if cfg.get("fold_calibration", "raw") == "threshold_ratio":
            cut = max(threshold(y[valid], fold_p, w[valid]), 1e-8)
            fold_q = np.mean(query_predictions[-replicas:], axis=0)
            aligned_query.append(fold_q / (fold_q + cut))
            fold_p = fold_p / (fold_p + cut)
        validation_p.append(fold_p)
        validation_w.append(w[valid])
    scores = np.mean(aligned_query if aligned_query else query_predictions, axis=0)
    if partition == "shared_calibration":
        validation_y, validation_w = validation_y[:1], validation_w[:1]
        validation_p = [np.mean(validation_p, axis=0)]
    # OOF calibration uses training labels only; query labels are never accessible.
    cut = select_alarm_threshold(np.concatenate(validation_y), np.concatenate(validation_p),
                                 np.concatenate(validation_w), cfg, diagnostics)
    if diagnostics is not None and partition == "shared_calibration":
        diagnostics["scope"] = "training_shared_calibration"
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
