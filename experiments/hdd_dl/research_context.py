"""Train-only aggregate profiling and bounded bibliographic retrieval.

Remote metadata is evidence, never executable instructions. Retrieved titles
only seed supported model-family hypotheses; no full-text findings are invented.
"""
from __future__ import annotations

import hashlib
import time
import urllib.parse

import httpx
import pandas as pd


def profile_training(public_files, gpu_available):
    labels = pd.read_csv(public_files["train_labels.csv"],
                         usecols=["serial_number", "label", "cutoff_date", "model"])
    if labels.serial_number.duplicated().any():
        raise ValueError("Training entity identity is not unique")
    counts = pd.Series(dtype="int64")
    rows = 0
    for chunk in pd.read_csv(public_files["train_history.csv.gz"],
                             usecols=["serial_number"], chunksize=100000):
        rows += len(chunk)
        counts = counts.add(chunk.serial_number.value_counts(), fill_value=0)
    n = len(labels)
    positives = int((labels.label == 1).sum())
    median_length = float(counts.median()) if len(counts) else 0.0
    # These are conservative engineering heuristics, not universal ML/DL cutoffs.
    allow_dl = bool(gpu_available and n >= 1000 and positives >= 50)
    families = ["mlp", "tcn", "gru", "dual"] if median_length >= 3 else ["mlp"]
    return {
        "training_entities": n, "training_history_rows": rows,
        "positive_entities": positives, "positive_fraction": positives / max(n, 1),
        "median_observations_per_entity": median_length,
        "model_categories": int(labels.model.nunique()),
        "independent_unit": "disk", "gpu_available": bool(gpu_available),
        "route": "ml_and_dl" if allow_dl else "ml_only",
        "dl_families": families if allow_dl else [],
        "reason": "Use entity count and positive support, not repeated history row count; compare by pilots.",
        "heuristic_policy": "v1:n_entities>=1000,n_positive>=50,gpu;sequence_median>=3",
        "scope": "training_only_no_query_labels",
    }


def metadata_card(item):
    title = " ".join(item.get("title", []))[:400]
    doi = item.get("DOI", "")
    if not isinstance(doi, str) or not doi.startswith("10.") or not title:
        return None
    lower = title.lower()
    relevant = any(s in lower for s in ["hard disk", "hard drive", "disk failure", "tabular"])
    if not relevant:
        return None
    if "convolution" in lower:
        family = "tcn"
    elif any(s in lower for s in ["recurrent", "lstm", "gru"]):
        family = "gru"
    elif any(s in lower for s in ["neural", "deep learning", "residual"]):
        family = "mlp"
    else:
        return None
    return {
        "id": "AUTO-" + hashlib.sha256(doi.encode()).hexdigest()[:10],
        "source": "https://doi.org/" + urllib.parse.quote(doi, safe="/"),
        "title": title, "type": "retrieval_lead", "verification": "bibliographic_metadata_only",
        "action": {"family": family},
        "claim": "Title suggests a relevant model family; full text and reported effectiveness are not verified.",
        "hypothesis": f"Evaluate the supported {family} family locally; this is not a reproduction of this paper.",
    }


def retrieve(profile, client=None):
    queries = ["hard disk failure prediction SMART deep neural network",
               "hard disk failure prediction temporal convolution recurrent"]
    if profile["median_observations_per_entity"] < 3:
        queries[1] = "tabular data residual neural network"
    owned = client is None
    client = client or httpx.Client(timeout=20, headers={
        "User-Agent": "FaultEvolveResearch/0.1 (https://github.com/houchenfeng/FaultEvolve-huawei)"})
    cards, events, seen = [], [], set()
    try:
        for query in queries:
            try:
                response = client.get("https://api.crossref.org/works", params={
                    "query.title": query, "rows": 6, "select": "DOI,title,URL,published"})
                response.raise_for_status()
                items = response.json()["message"]["items"]
                added = 0
                for item in items:
                    card = metadata_card(item)
                    if card and card["id"] not in seen:
                        seen.add(card["id"])
                        cards.append(card)
                        added += 1
                events.append({"query": query, "status": "ok", "results": len(items), "cards": added})
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                events.append({"query": query, "status": "unavailable", "error_type": type(exc).__name__})
    finally:
        if owned:
            client.close()
    return {"provider": "Crossref", "retrieved_at": time.time(), "events": events, "cards": cards,
            "fallback": "Curated cards remain active if retrieval yields no supported leads.",
            "raw_data_uploaded": False}
