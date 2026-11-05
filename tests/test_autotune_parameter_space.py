"""Parameter space validation tests."""

import numpy as np
import pytest

from faultevolve.optimization.parameter_space import ParameterSpaceError, ParamDef, validate_values
from faultevolve.tasks.hdd_space import logreg_space


def test_p2_log_low_raises():
    with pytest.raises(Exception):
        ParamDef(name="C", kind="float", low=0, high=1, log=True)


def test_p5_sampling_self_consistent():
    space = logreg_space()
    rng = np.random.default_rng(0)
    from faultevolve.optimization.parameter_space import sample

    for _ in range(200):
        vals = sample(space, rng)
        assert validate_values(space, vals) == []
