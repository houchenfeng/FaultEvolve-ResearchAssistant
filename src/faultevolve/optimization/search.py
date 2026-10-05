"""Searcher protocol and random search implementation."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from faultevolve.optimization.parameter_space import ParameterSpace, sample
from faultevolve.optimization.trials import Trial


class Searcher(Protocol):
    def propose(
        self,
        space: ParameterSpace,
        *,
        structure_id: str,
        start_index: int,
        n: int,
    ) -> list[dict]: ...

    def observe(self, trial: Trial) -> None: ...


class RandomSearch:
    def __init__(self, seed: int) -> None:
        self._seed = seed

    def _rng(self, structure_id: str, index: int) -> np.random.Generator:
        struct_seed = int(structure_id.replace("sha256:", "")[:8], 16)
        return np.random.default_rng(
            np.random.SeedSequence([self._seed, struct_seed, index])
        )

    def propose(
        self,
        space: ParameterSpace,
        *,
        structure_id: str,
        start_index: int,
        n: int,
    ) -> list[dict]:
        out: list[dict] = []
        for k in range(start_index, start_index + n):
            rng = self._rng(structure_id, k)
            out.append(sample(space, rng))
        return out

    def observe(self, trial: Trial) -> None:
        return None
