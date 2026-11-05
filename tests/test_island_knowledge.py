"""S4 D4.1: three trees read one knowledge library for three different questions.

TODO tests T15/T16. An island profile earns its name only when that island's
search sees different material: same frozen library, same retriever, different
keywords, therefore different cards. Everything here is offline (MockLLM +
FakeAdapter), so every score asserted is a number the local evaluator produced --
a card may suggest a method, never a score, and a knowledge service that is down
must not change one either.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from faultevolve.cloud.engine import EvolutionEngine
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.store import Store
from faultevolve.common.schemas import Insight
from faultevolve.config import EvolveConfig
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec

from tests.test_island_exchange import _take_attempt
from tests.test_island_isolation import (
    _RecordingLLM,
    _island_states,
    _tree_of,
    _valid,
)


@pytest.fixture
def temp_db(tmp_path):
    """A state db in the run-dir layout, so run-level knowledge paths resolve here.

    :meth:`EvolutionEngine._discovery_card_path` walks two directories up from the
    db, so a flat temp file would point the shared card pool outside the test.
    """
    db_path = tmp_path / "runs" / "run-1" / "state.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


@pytest.fixture
def task_dir(tmp_path):
    (tmp_path / "evaluator.py").write_text("SCORE = 1\n", encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    return tmp_path


def _card(card_id: str, category: str, tags: list[str]) -> dict[str, Any]:
    return {
        "id": card_id,
        "title": f"card {card_id}",
        "category": category,
        "claim": f"claim of {card_id}",
        "source_ids": ["paper-1"],
        "tags": tags,
        "impl_hint": "hint",
        "risk": "risk",
        "priority": 3,
    }


#: One pair of cards per island keyword family, in six different categories, so
#: what separates the islands can only be the keywords they each carry.
LIBRARY = [
    _card("K-A1", "feature_engineering", ["temporal", "pattern"]),
    _card("K-A2", "model", ["nonlinear"]),
    _card("K-B1", "imbalance", ["imbalanced", "learning"]),
    _card("K-B2", "thresholding", ["threshold", "calibration"]),
    _card("K-C1", "pitfalls", ["redundant", "features"]),
    _card("K-C2", "evaluation", ["stability"]),
]


def _dump(path: Path, cards: list[dict[str, Any]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cards) + "\n",
        encoding="utf-8",
    )
    return path


def _library(task_dir: Path, cards: list[dict[str, Any]] | None = None) -> Path:
    return _dump(task_dir / "knowledge" / "cards.jsonl", cards if cards is not None else LIBRARY)


def _config(*, k: int = 2) -> EvolveConfig:
    """Three default islands -- and therefore three default keyword sets."""
    config = EvolveConfig()
    config.budget.max_iterations = 30
    config.budget.max_wall_hours = 0.5
    config.budget.stall_iterations = 100
    config.smoke_test.enabled = False
    config.operators.enabled = ["refine"]
    config.operators.bandit = False
    config.islands.exchange_interval = 1
    config.knowledge.dir = "knowledge"
    config.knowledge.k = k
    config.knowledge.max_per_category = 1
    return config


def _engine(
    temp_db: Path,
    task_dir: Path,
    adapter: FakeAdapter,
    config: EvolveConfig,
    llm: Any = None,
) -> EvolutionEngine:
    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=FakeTaskSpec(
            task_dir=task_dir,
            problem_md="predict failing units",
            prompt_md="SHARED-TASK-INSTRUCTION",
            init_code='"""init"""\npass\n',
        ),
        store=Store(temp_db),
        llm=llm or MockLLM(),
        mock=True,
        task_dir=task_dir,
    )
    engine.initialize()
    return engine


def _injections(engine: EvolutionEngine) -> list[dict[str, Any]]:
    return [
        e.payload
        for e in engine.store.get_events(engine.experiment_id)
        if e.type == "knowledge_injected"
    ]


def _injection_for(engine: EvolutionEngine, island_id: str) -> dict[str, Any]:
    matches = [p for p in _injections(engine) if p["island_id"] == island_id]
    assert matches, f"island {island_id} never recorded a knowledge selection"
    return matches[-1]


class _DeclaringLLM(_RecordingLLM):
    """MockLLM's answer with its adoption claim rewritten to the injected card.

    Provenance is tested against what the candidate said it used, so the declared
    id has to be the one the extractor reads: MockLLM's canned reply already
    carries an <adopted_cards> block, and the parser takes the first tag, which is
    why this replaces it instead of appending another.
    """

    def __init__(self, card_id: str) -> None:
        super().__init__()
        self.card_id = card_id

    def chat(self, messages, **kwargs: Any):
        text, metrics = super().chat(messages, **kwargs)
        declared = f"<adopted_cards>{self.card_id}</adopted_cards>"
        text, hits = re.subn(
            r"<adopted_cards>.*?</adopted_cards>", declared, text, flags=re.DOTALL
        )
        if not hits:
            text = f"{text}\n{declared}"
        return text, metrics


def _results(init_score: float = 20.0, child_score: float = 25.0) -> list[dict[str, Any]]:
    """One shared real init evaluation, then only good candidates.

    Uniform child scores on purpose: a MockLLM repair chain can consume more than
    one evaluation per attempt, and the assertions here are about which number is
    the evaluator's, not how many calls it took to get there.
    """
    return [_valid(init_score)] + [_valid(child_score)] * 14


# ---------------------------------------------------------------------------
# T15 -- the cards a candidate was handed are recorded, per island
# ---------------------------------------------------------------------------


def test_each_island_reads_the_library_for_its_own_keywords(temp_db, task_dir):
    _library(task_dir)
    adapter = FakeAdapter()
    adapter.set_results(_results())
    config = _config()
    engine = _engine(temp_db, task_dir, adapter, config)

    for island_id in ("a", "b", "c"):
        _take_attempt(engine, island_id)

    selected = {iid: set(_injection_for(engine, iid)["card_ids"]) for iid in ("a", "b", "c")}
    assert selected["a"], "an island with a matching library got no card at all"
    assert selected["b"] and selected["c"], selected
    assert len({frozenset(v) for v in selected.values()}) == 3, (
        f"three islands selected the same cards: {selected}"
    )
    assert "K-A1" in selected["a"]
    assert {"K-B1", "K-B2"} == selected["b"]
    assert "K-C1" in selected["c"]
    # The keywords that did it are recorded, not guessed afterwards from card ids.
    for island_id in ("a", "b", "c"):
        payload = _injection_for(engine, island_id)
        own = next(
            s.knowledge_keywords for s in config.islands.islands if s.island_id == island_id
        )
        assert payload["island_keywords"] == own
        assert payload["profile"]


def test_an_injected_card_reaches_the_prompt_and_the_candidate_record(temp_db, task_dir):
    """Provenance means the card id is on the candidate, not that a flag was on."""
    _library(task_dir)
    adapter = FakeAdapter()
    adapter.set_results(_results())
    llm = _DeclaringLLM("K-A1")
    engine = _engine(temp_db, task_dir, adapter, _config(), llm)

    _take_attempt(engine, "a")

    payload = _injection_for(engine, "a")
    assert "K-A1" in payload["card_ids"]
    assert payload["selected"] is True
    assert payload["parent_id"]
    # Every offered card came from the task's frozen library and nothing else: a
    # grouped origin list is the honest answer to "where did this card come from".
    assert payload["sources"] == {"frozen": sorted(payload["card_ids"])}

    prompts = [p for p in llm.prompts if "SHARED-TASK-INSTRUCTION" in p]
    assert any("**K-A1**" in p for p in prompts), "the card id never reached a prompt"

    tree = _tree_of(engine, "a")
    child = next(n for n in tree.nodes.values() if n.parent_id == tree.root_id)
    assert child.card_ids == ["K-A1"]
    stored = engine.store.get_node(child.id)
    assert stored is not None and stored.card_ids == ["K-A1"]
    assert stored.evidence.evaluation.combined_score == 25.0, (
        "the candidate keeps the evaluator's number, not a card's suggestion"
    )


def test_a_card_this_run_produced_is_labelled_run_new(temp_db, task_dir):
    _library(task_dir)
    produced = _dump(
        task_dir / "discovered_cards.jsonl",
        [_card("RN-1", "transfer", ["temporal"])],
    )
    config = _config(k=3)
    config.discovery.enabled = True
    config.discovery.inject_same_run = True
    config.discovery.every_n_iterations = 10_000
    config.discovery.extra_card_paths = [str(produced)]

    adapter = FakeAdapter()
    adapter.set_results(_results())
    engine = _engine(temp_db, task_dir, adapter, config)

    _take_attempt(engine, "a")

    sources = _injection_for(engine, "a")["sources"]
    assert sources.get("run_new") == ["RN-1"], sources
    assert "RN-1" not in sources.get("frozen", []), sources
    assert set(sources) == {"frozen", "run_new"}


def test_experience_promoted_on_one_island_is_knowledge_for_the_others(temp_db, task_dir):
    """Discovery writes one run-level card file, so that file is shared knowledge.

    The card below is placed exactly where the engine's own promotion writes
    (:meth:`EvolutionEngine._discovery_card_path`), then read by an island that did
    not produce it. It has to arrive labelled ``run_new`` -- sharing the pool must
    not blur it into the task's frozen library, or a run would end up citing its
    own one-off observation as prior domain knowledge. ``k`` is set to the number
    of categories in the pool, so this proves reachability rather than depending on
    where the retriever ranked the card.
    """
    _library(task_dir)
    config = _config(k=7)
    config.discovery.enabled = True
    config.discovery.inject_same_run = True
    config.discovery.every_n_iterations = 10_000

    adapter = FakeAdapter()
    adapter.set_results(_results())
    engine = _engine(temp_db, task_dir, adapter, config)

    pool = engine._discovery_card_path()
    assert str(pool).endswith("discovered_cards.jsonl")
    pool.parent.mkdir(parents=True, exist_ok=True)
    _dump(pool, [_card("RN-B", "transfer", ["imbalanced", "learning"])])

    _take_attempt(engine, "b")

    payload = _injection_for(engine, "b")
    assert "RN-B" in payload["card_ids"]
    assert "RN-B" in payload["sources"]["run_new"]
    assert "RN-B" not in payload["sources"].get("frozen", [])


# ---------------------------------------------------------------------------
# An empty selection is a fact with a reason, not a silent gap
# ---------------------------------------------------------------------------


def test_knowledge_switched_off_is_recorded_as_off(temp_db, task_dir):
    _library(task_dir)
    config = _config()
    config.knowledge.enabled = False
    adapter = FakeAdapter()
    adapter.set_results(_results())
    engine = _engine(temp_db, task_dir, adapter, config)

    _take_attempt(engine, "a")

    payload = _injection_for(engine, "a")
    assert payload["reason"] == "knowledge_disabled"
    assert payload["selected"] is False and payload["card_ids"] == []


def test_a_task_without_a_knowledge_source_says_so(temp_db, task_dir):
    config = _config()
    config.knowledge.dir = "no_such_library"
    adapter = FakeAdapter()
    adapter.set_results(_results())
    engine = _engine(temp_db, task_dir, adapter, config)

    _take_attempt(engine, "a")

    assert _injection_for(engine, "a")["reason"] == "no_knowledge_source"


def test_a_library_that_will_not_parse_selects_nothing_and_says_why(temp_db, task_dir):
    _library(task_dir, [{"id": "BAD-1", "category": "not_a_category", "claim": "x"}])
    adapter = FakeAdapter()
    adapter.set_results(_results())
    engine = _engine(temp_db, task_dir, adapter, _config())

    _take_attempt(engine, "a")

    payload = _injection_for(engine, "a")
    assert payload["reason"] == "no_applicable_card"
    assert payload["selected"] is False
    assert _island_states(engine)["a"].best_score == 25.0, (
        "an unusable library must still not touch the evaluator's number"
    )


# ---------------------------------------------------------------------------
# T16 -- a knowledge service that fails is recorded as failing
# ---------------------------------------------------------------------------


def test_a_broken_knowledge_service_changes_no_score(temp_db, task_dir, monkeypatch):
    _library(task_dir)
    adapter = FakeAdapter()
    adapter.set_results(_results())
    llm = _RecordingLLM()
    engine = _engine(temp_db, task_dir, adapter, _config(), llm)

    def explode(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("knowledge service down")

    import faultevolve.cloud.engine as engine_module

    monkeypatch.setattr(engine_module, "get_era_knowledge_cards", explode)
    _take_attempt(engine, "a")

    payload = _injection_for(engine, "a")
    assert payload["reason"] == "retrieval_failed"
    assert payload["error_type"] == "RuntimeError"
    assert payload["card_ids"] == [] and payload["sources"] == {}
    # The attempt still happened, and its number is still the evaluator's.
    assert any("SHARED-TASK-INSTRUCTION" in p for p in llm.prompts)
    states = _island_states(engine)
    assert states["a"].best_score == 25.0
    assert states["a"].attempts >= 1


# ---------------------------------------------------------------------------
# Discovery harvest is island-local too (explicit, not an accident of the tree)
# ---------------------------------------------------------------------------


def test_a_discovery_round_harvests_only_the_island_that_asked(temp_db, task_dir):
    _library(task_dir)
    adapter = FakeAdapter()
    adapter.set_results(_results())
    config = _config()
    config.discovery.enabled = True
    config.discovery.min_insight_z = 0.5
    engine = _engine(temp_db, task_dir, adapter, config)

    origins: dict[str, str] = {}
    for island_id in ("a", "b"):
        _take_attempt(engine, island_id)
        tree = _tree_of(engine, island_id)
        child = next(n for n in tree.nodes.values() if n.parent_id == tree.root_id)
        origins[island_id] = child.id
        engine.store.create_insight(
            Insight(
                id=f"ins-{island_id}",
                origin_node=child.id,
                branch_id=child.branch_id,
                island_id=island_id,
                polarity=1,
                change_summary=f"{island_id} improved",
                z_score=2.0,
            ),
            engine.experiment_id,
        )

    engine._activate_island("a")
    harvested = {item[0] for item in engine._harvest_discovery_candidates()}
    assert origins["a"] in harvested
    assert origins["b"] not in harvested, (
        "a discovery round reached into a sibling island's insights"
    )
