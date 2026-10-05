"""Deterministic train/confirm splits for discovery."""

from __future__ import annotations

import hashlib
from typing import Literal

import numpy as np
import pandas as pd


def assign_split(
    unit_id: str,
    salt: str,
    confirmation_fraction: float,
) -> Literal["explore", "confirm"]:
    digest = hashlib.sha256(f"{salt}|{unit_id}".encode()).digest()
    val = int.from_bytes(digest[:8], "big") / (2**64)
    if val < confirmation_fraction:
        return "confirm"
    return "explore"


def split_masks(
    labels: pd.DataFrame,
    unit_col: str,
    salt: str,
    fraction: float,
) -> tuple[np.ndarray, np.ndarray]:
    units = labels[unit_col].astype(str).tolist()
    explore = []
    confirm = []
    for u in units:
        if assign_split(u, salt, fraction) == "confirm":
            confirm.append(True)
            explore.append(False)
        else:
            confirm.append(False)
            explore.append(True)
    return np.array(explore, dtype=bool), np.array(confirm, dtype=bool)


def label_times(
    labels: pd.DataFrame,
    unit_col: str,
    time_col: str,
    env_frame: pd.DataFrame | None = None,
    history: pd.DataFrame | None = None,
) -> pd.Series | None:
    """Per-label-row calendar times, or None when no real time column is available."""
    n = len(labels)
    if time_col and time_col in labels.columns:
        return labels[time_col]
    if env_frame is not None and "time" in env_frame.columns and len(env_frame) == n:
        return env_frame["time"]
    if (
        history is not None
        and not history.empty
        and time_col
        and time_col in history.columns
        and unit_col in labels.columns
        and unit_col in history.columns
    ):
        per_unit = history.groupby(unit_col, sort=False)[time_col].max()
        mapped = labels[unit_col].map(per_unit)
        if mapped.notna().any():
            return mapped
    return None


def temporal_halves(times: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    unique_times = sorted(times.dropna().unique())
    if not unique_times:
        n = len(times)
        mid = n // 2
        first = np.zeros(n, dtype=bool)
        second = np.zeros(n, dtype=bool)
        first[:mid] = True
        second[mid:] = True
        return first, second
    mid_time = unique_times[len(unique_times) // 2]
    first = (times <= mid_time).to_numpy(dtype=bool)
    second = (times > mid_time).to_numpy(dtype=bool)
    return first, second
