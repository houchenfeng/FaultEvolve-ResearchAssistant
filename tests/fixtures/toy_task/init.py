"""Toy initial solution for testing."""

import argparse
import os

import numpy as np
import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    np.random.seed(42)
    n_samples = 100

    pred = pd.DataFrame({
        "serial_number": [f"SN{i:06d}" for i in range(n_samples)],
        "score": np.random.rand(n_samples) * 0.5 + 0.25,
        "alarm": np.random.randint(0, 2, n_samples),
    })

    pred.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
