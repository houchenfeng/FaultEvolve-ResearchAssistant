"""In-process copies of the before/after programs for streaming scoring.

The candidate programs are CLI scripts (read files, write a CSV). For the live
stream we need fitted models we can call on a few hundred disks per frame, so each
wrapper imports the program as a module and reproduces its ``main()`` step by step
with the program's own functions. Training uses only the local public train split.
"""

from __future__ import annotations

import importlib.util
import pickle
import threading
import time
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd

from faultevolve.edge import paths


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _file_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()[:12]


class _ProgramBacked:
    """Pickles without the imported program module; re-imports it on load."""

    program: Path
    module_name: str
    mod: ModuleType

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state.pop("mod", None)
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        self.mod = _load_module(self.program, self.module_name)


@dataclass
class Prediction:
    serials: list[str]
    scores: np.ndarray
    alarms: np.ndarray

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame({"serial_number": self.serials, "score": self.scores, "alarm": self.alarms})


class BaselineModel(_ProgramBacked):
    """``init.py``: logistic regression on the last snapshot before cutoff."""

    key = "before"
    label = "进化前 · init.py"

    def __init__(self, program: Path = paths.BASELINE_PROGRAM) -> None:
        self.program = program
        self.module_name = "fe_edge_baseline"
        self.mod = _load_module(program, self.module_name)
        self.model: Any = None
        self.threshold = 0.5

    def fit(self) -> None:
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        hist = pd.read_csv(paths.PUBLIC_DIR / "train_history.csv.gz", parse_dates=["date"])
        lab = pd.read_csv(paths.PUBLIC_DIR / "train_labels.csv").set_index("serial_number")
        x = self.mod.last_snapshot(hist).reindex(lab.index).fillna(0.0)
        y = lab["label"].to_numpy()
        w = lab["weight"].to_numpy()
        self.model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5))
        self.model.fit(x, y, logisticregression__sample_weight=w)
        self.threshold = self.mod.best_f1_threshold(y, self.model.predict_proba(x)[:, 1], w)
        self.columns = list(x.columns)

    def predict(self, hist: pd.DataFrame, cutoffs: pd.DataFrame) -> Prediction:
        serials = cutoffs["serial_number"].astype(str).tolist()
        x = self.mod.last_snapshot(hist).reindex(serials).reindex(columns=self.columns).fillna(0.0)
        p = self.model.predict_proba(x)[:, 1]
        return Prediction(serials, p, (p >= self.threshold).astype(int))


class EvolvedModel(_ProgramBacked):
    """Cloud-evolved best node: windowed SMART features + LightGBM ensemble."""

    key = "after"
    label = f"进化后 · {paths.EVOLVED_NODE_ID}"

    def __init__(self, program: Path = paths.EVOLVED_PROGRAM) -> None:
        self.program = program
        self.module_name = "fe_edge_evolved"
        self.mod = _load_module(program, self.module_name)
        self.models: list[Any] = []
        self.columns: list[str] = []
        self.threshold = float("inf")

    def _matrix(self, x: pd.DataFrame) -> np.ndarray:
        x = x.reindex(columns=self.columns, fill_value=np.nan)
        miss = [c for c in self.columns if c.endswith("_missing")]
        if miss:
            x[miss] = x[miss].fillna(1.0)
        return x.astype("float32").to_numpy()

    def _score(self, matrix: np.ndarray) -> np.ndarray:
        total = np.zeros(matrix.shape[0], dtype="float64")
        for model in self.models:
            total += model.predict_proba(matrix)[:, 1]
        return np.nan_to_num(total / max(len(self.models), 1), nan=0.0, posinf=1.0, neginf=0.0)

    def fit(self) -> None:
        from sklearn.model_selection import StratifiedKFold

        m = self.mod
        lab = pd.read_csv(paths.PUBLIC_DIR / "train_labels.csv", parse_dates=["cutoff_date"])
        lab = lab.drop_duplicates(subset=["serial_number"], keep="last").reset_index(drop=True)
        serials = lab["serial_number"].astype("object")
        y = np.where(np.nan_to_num(lab["label"].to_numpy(dtype="float64")) > 0, 1, 0).astype("int32")
        w = np.nan_to_num(lab["weight"].to_numpy(dtype="float64"), nan=1.0)
        w = np.where(w > 0, w, 1.0)

        x_tr = m.build_features(m.read_history(paths.PUBLIC_DIR / "train_history.csv.gz"), lab).reindex(serials)
        self.columns = list(x_tr.columns)
        x = self._matrix(x_tr)

        skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=0)
        oof = np.zeros(x.shape[0], dtype="float64")
        for train_idx, val_idx in skf.split(x, y):
            for cfg in m.CONFIGS:
                model = m.make_model(
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
                self.models.append(model)
        oof /= float(len(m.CONFIGS))
        self._oof = np.nan_to_num(oof, nan=0.0, posinf=1.0, neginf=0.0)
        self.threshold = float(m.choose_threshold(self._oof, y, w))

    def calibrate_on(self, query_scores: np.ndarray) -> None:
        """Apply the program's query-distribution threshold fallback once, on the full val split."""
        threshold = self.threshold
        oof_frac = float(np.mean(self._oof >= threshold)) if len(self._oof) else 0.0
        if oof_frac <= 0.0:
            threshold = float(np.max(query_scores) + 1.0)
        elif oof_frac >= 1.0:
            threshold = float(np.min(query_scores) - 1.0)
        else:
            direct = float(np.mean(query_scores >= threshold))
            if direct <= 0.0 or direct > 4.0 * oof_frac or direct < 0.25 * oof_frac:
                threshold = float(np.quantile(query_scores, 1.0 - oof_frac))
        self.threshold = threshold

    def predict(self, hist: pd.DataFrame, cutoffs: pd.DataFrame) -> Prediction:
        serials = cutoffs["serial_number"].astype("object")
        x = self.mod.build_features(hist, cutoffs).reindex(serials)
        p = self._score(self._matrix(x))
        return Prediction(serials.astype(str).tolist(), p, (p >= self.threshold).astype(int))


@dataclass
class ModelBundle:
    before: BaselineModel
    after: EvolvedModel
    val_before: Prediction
    val_after: Prediction
    fit_seconds: float
    digests: dict[str, str] = field(default_factory=dict)


def _val_inputs(evolved: EvolvedModel) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    idx = pd.read_csv(paths.PUBLIC_DIR / "val_index.csv", parse_dates=["cutoff_date"])
    hist_full = pd.read_csv(paths.PUBLIC_DIR / "val_history.csv.gz", parse_dates=["date"])
    hist_evolved = evolved.mod.read_history(paths.PUBLIC_DIR / "val_history.csv.gz")
    return idx, hist_full, hist_evolved


def train_bundle() -> ModelBundle:
    """Fit both programs on the local train split and score the full val split once."""
    digests = {"before": _file_digest(paths.BASELINE_PROGRAM), "after": _file_digest(paths.EVOLVED_PROGRAM)}
    cache = paths.CACHE_DIR / f"bundle_{digests['before']}_{digests['after']}.pkl"
    if cache.exists():
        try:
            with cache.open("rb") as fh:
                bundle: ModelBundle = pickle.load(fh)
            return bundle
        except Exception:
            cache.unlink(missing_ok=True)

    started = time.perf_counter()
    before = BaselineModel()
    before.fit()
    after = EvolvedModel()
    after.fit()

    idx, hist_full, hist_evolved = _val_inputs(after)
    after_scores = after.predict(hist_evolved, idx)
    after.calibrate_on(after_scores.scores)
    val_after = Prediction(after_scores.serials, after_scores.scores, (after_scores.scores >= after.threshold).astype(int))
    val_before = before.predict(hist_full, idx)

    bundle = ModelBundle(before, after, val_before, val_after, time.perf_counter() - started, digests)
    paths.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with cache.open("wb") as fh:
            pickle.dump(bundle, fh)
    except Exception:
        cache.unlink(missing_ok=True)
    return bundle


class ModelService:
    """Train once in the background; callers wait on ``get``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self.bundle: ModelBundle | None = None
        self.status = "idle"
        self.error: str | None = None
        self.started_at: float | None = None

    def ensure_started(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self.status = "training"
            self.started_at = time.time()
            self._thread = threading.Thread(target=self._run, name="fe-edge-train", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            self.bundle = train_bundle()
            self.status = "ready"
        except Exception as exc:  # surfaced to the UI, not swallowed
            self.status = "error"
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._ready.set()

    def get(self, timeout: float | None = None) -> ModelBundle:
        self.ensure_started()
        self._ready.wait(timeout)
        if self.bundle is None:
            raise RuntimeError(self.error or "models not ready")
        return self.bundle

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"status": self.status, "error": self.error}
        if self.bundle is not None:
            info.update(
                fit_seconds=round(self.bundle.fit_seconds, 1),
                before={"label": BaselineModel.label, "threshold": round(float(self.bundle.before.threshold), 5), "sha": self.bundle.digests.get("before")},
                after={"label": EvolvedModel.label, "threshold": round(float(self.bundle.after.threshold), 5), "sha": self.bundle.digests.get("after"), "ensemble": len(self.bundle.after.models)},
            )
        return info
