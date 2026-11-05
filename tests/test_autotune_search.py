"""Random search reproducibility."""

import pytest

from faultevolve.optimization.search import RandomSearch
from faultevolve.tasks.hdd_space import logreg_space


def test_s1_propose_chunk_invariant():
    space = logreg_space()
    rs = RandomSearch(42)
    a = rs.propose(space, structure_id="sha256:abcd1234", start_index=0, n=8)
    b = rs.propose(space, structure_id="sha256:abcd1234", start_index=0, n=4)
    b += rs.propose(space, structure_id="sha256:abcd1234", start_index=4, n=4)
    assert a == b


def test_s4_tpe_rejected_in_config():
    from faultevolve.config import EvolveConfig

    with pytest.raises(ValueError):
        EvolveConfig.from_dict({"autotune": {"hpo": {"search": "tpe"}}})
