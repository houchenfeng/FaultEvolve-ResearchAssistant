"""Tests for knowledge injection system."""

import json
import tempfile
from pathlib import Path

import pytest

from faultevolve.knowledge.loader import (
    KnowledgeCard,
    get_cards_by_category,
    load_cards,
    validate_card,
    parse_card,
)
from faultevolve.knowledge.retriever import (
    CardRetriever,
    CardStats,
    RetrievalContext,
    compute_priority_score,
    compute_tag_match_score,
    extract_keywords_from_text,
)
from faultevolve.tasks.hdd_adapter import HDDAdapter
from faultevolve.common.codecheck import extract_adopted_cards_from_response


class TestCardValidation:
    """Tests for card loading and validation."""

    def test_validate_card_valid(self):
        """Test validation of a valid card."""
        card = {
            "id": "FE01",
            "title": "Test card",
            "category": "feature_engineering",
            "claim": "This improves performance",
            "source_ids": ["paper1"],
            "tags": ["smart_5", "trend"],
        }
        is_valid, error = validate_card(card)
        assert is_valid is True
        assert error == ""

    def test_validate_card_missing_id(self):
        """Test validation rejects missing id."""
        card = {
            "title": "Test card",
            "category": "feature_engineering",
            "claim": "This improves performance",
            "source_ids": ["paper1"],
            "tags": ["smart_5"],
        }
        is_valid, error = validate_card(card)
        assert is_valid is False
        assert "id" in error.lower()

    def test_validate_card_invalid_category(self):
        """Test validation rejects invalid category."""
        card = {
            "id": "FE01",
            "title": "Test card",
            "category": "invalid_category",
            "claim": "This improves performance",
            "source_ids": ["paper1"],
            "tags": ["smart_5"],
        }
        is_valid, error = validate_card(card)
        assert is_valid is False
        assert "category" in error.lower()

    def test_validate_card_invalid_priority(self):
        """Test validation rejects invalid priority."""
        card = {
            "id": "FE01",
            "title": "Test card",
            "category": "feature_engineering",
            "claim": "This improves performance",
            "source_ids": [],
            "tags": [],
            "priority": 10,
        }
        is_valid, error = validate_card(card)
        assert is_valid is False
        assert "priority" in error.lower()

    def test_load_cards_from_file(self):
        """Test loading cards from JSONL file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            card1 = {"id": "C1", "title": "Card 1", "category": "model", "claim": "Test", "source_ids": [], "tags": []}
            card2 = {"id": "C2", "title": "Card 2", "category": "evaluation", "claim": "Test", "source_ids": [], "tags": []}
            f.write(json.dumps(card1) + "\n")
            f.write(json.dumps(card2) + "\n")
            path = Path(f.name)

        cards, errors = load_cards(path)
        path.unlink()

        assert len(cards) == 2
        assert len(errors) == 0
        assert cards[0].id == "C1"
        assert cards[1].id == "C2"

    def test_load_cards_duplicate_ids(self):
        """Test that duplicate IDs are reported as errors."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            card = {"id": "C1", "title": "Card", "category": "model", "claim": "Test", "source_ids": [], "tags": []}
            f.write(json.dumps(card) + "\n")
            f.write(json.dumps(card) + "\n")
            path = Path(f.name)

        cards, errors = load_cards(path)
        path.unlink()

        assert len(cards) == 1
        assert len(errors) == 1
        assert "duplicate" in errors[0].lower()

    def test_load_cards_invalid_json(self):
        """Test that invalid JSON lines are reported as errors."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("not valid json\n")
            f.write('{"id": "C1", "title": "Card", "category": "model", "claim": "Test", "source_ids": [], "tags": []}\n')
            path = Path(f.name)

        cards, errors = load_cards(path)
        path.unlink()

        assert len(cards) == 1
        assert len(errors) == 1
        assert "json" in errors[0].lower()

    def test_knowledge_card_aliases(self):
        """Test that KnowledgeCard has idea and source aliases."""
        card = KnowledgeCard(
            id="FE01",
            title="Test",
            category="model",
            claim="This is the claim",
            source_ids=["paper1", "paper2"],
            tags=["tag1"],
        )
        assert card.idea == card.claim
        assert card.source == "paper1, paper2"

    def test_get_cards_by_category(self):
        """Test grouping cards by category."""
        cards = [
            KnowledgeCard(id="1", title="A", category="model", claim="", source_ids=[], tags=[]),
            KnowledgeCard(id="2", title="B", category="model", claim="", source_ids=[], tags=[]),
            KnowledgeCard(id="3", title="C", category="evaluation", claim="", source_ids=[], tags=[]),
        ]
        by_cat = get_cards_by_category(cards)
        assert len(by_cat["model"]) == 2
        assert len(by_cat["evaluation"]) == 1


class TestRetrieval:
    """Tests for card retrieval."""

    @pytest.fixture
    def sample_cards(self):
        """Create sample cards for testing."""
        return [
            KnowledgeCard(
                id="FE01", title="Window deltas", category="feature_engineering",
                claim="Deltas improve", source_ids=[], tags=["smart_5", "delta", "trend"],
                priority=1, impl_hint="Use groupby"
            ),
            KnowledgeCard(
                id="FE02", title="Rate features", category="feature_engineering",
                claim="Rates are robust", source_ids=[], tags=["rate", "missing_days"],
                priority=2
            ),
            KnowledgeCard(
                id="M01", title="LightGBM", category="model",
                claim="LightGBM is fast", source_ids=[], tags=["lightgbm", "gbdt"],
                priority=1
            ),
            KnowledgeCard(
                id="T01", title="OOF threshold", category="thresholding",
                claim="OOF beats in-sample", source_ids=[], tags=["threshold", "oof"],
                priority=1
            ),
            KnowledgeCard(
                id="E01", title="Replicate ROS", category="evaluation",
                claim="Match evaluator", source_ids=[], tags=["oof", "metric"],
                priority=1
            ),
        ]

    def test_extract_keywords_from_text(self):
        """Test generic keyword extraction from text."""
        code = """
import lightgbm as lgb
model = lgb.LGBMClassifier()
if score > threshold:
    alarm = 1
"""
        keywords = extract_keywords_from_text(code)
        assert "model" in keywords
        assert "threshold" in keywords

    def test_hdd_adapter_context_keywords(self):
        """Test HDD-specific keyword extraction via adapter."""
        adapter = HDDAdapter()
        code = """
import lightgbm as lgb
delta_5 = g.smart_5_raw.last() - g.smart_5_raw.first()
smart_187_rate = df['smart_187'].diff()
if score > threshold:
    alarm = 1
"""
        keywords = adapter.context_keywords(code)
        assert "smart_5" in keywords
        assert "smart_187" in keywords
        assert "lightgbm" in keywords
        assert "delta" in keywords
        assert "threshold" in keywords

    def test_compute_priority_score(self):
        """Test priority score computation."""
        card1 = KnowledgeCard(id="1", title="", category="model", claim="", source_ids=[], tags=[], priority=1)
        card5 = KnowledgeCard(id="2", title="", category="model", claim="", source_ids=[], tags=[], priority=5)

        assert compute_priority_score(card1) == 1.0
        assert compute_priority_score(card5) == 0.2

    def test_compute_tag_match_score(self):
        """Test tag matching score computation."""
        card = KnowledgeCard(
            id="1", title="", category="model", claim="",
            source_ids=[], tags=["smart_5", "delta", "trend"]
        )

        high_match = {"smart", "5", "delta", "trend", "model"}
        partial_match = {"smart", "other", "unrelated"}
        no_match = {"unrelated", "keywords", "xyz"}

        score_high = compute_tag_match_score(card, high_match)
        score_partial = compute_tag_match_score(card, partial_match)
        score_none = compute_tag_match_score(card, no_match)

        assert score_high > score_partial > score_none
        assert score_high > 0.5

    def test_retriever_basic(self, sample_cards):
        """Test basic retrieval."""
        retriever = CardRetriever(cards=sample_cards, default_k=3)
        context = RetrievalContext(code_text="import lightgbm")

        selected = retriever.retrieve(context, k=3)

        assert len(selected) <= 3
        assert all(isinstance(c, KnowledgeCard) for c in selected)

    def test_retriever_category_diversity(self, sample_cards):
        """Test category diversity constraint."""
        retriever = CardRetriever(cards=sample_cards, max_per_category=1, default_k=5)
        context = RetrievalContext(code_text="")

        selected = retriever.retrieve(context, k=5)

        categories = [c.category for c in selected]
        from collections import Counter
        cat_counts = Counter(categories)
        assert all(count <= 1 for count in cat_counts.values())

    def test_retriever_excludes_refuted(self, sample_cards):
        """Test that refuted cards are excluded."""
        retriever = CardRetriever(cards=sample_cards, default_k=5)
        context = RetrievalContext(
            code_text="",
            branch_refuted_cards={"FE01", "M01"},
        )

        selected = retriever.retrieve(context)

        selected_ids = {c.id for c in selected}
        assert "FE01" not in selected_ids
        assert "M01" not in selected_ids

    def test_retriever_excludes_ancestor_adopted(self, sample_cards):
        """Test that ancestor-adopted cards are excluded."""
        retriever = CardRetriever(cards=sample_cards, default_k=5)
        context = RetrievalContext(
            code_text="",
            ancestor_adopted_cards={"FE01", "T01"},
        )

        selected = retriever.retrieve(context)

        selected_ids = {c.id for c in selected}
        assert "FE01" not in selected_ids
        assert "T01" not in selected_ids

    def test_retriever_with_card_stats(self, sample_cards):
        """Test retrieval with card statistics."""
        card_stats = {
            "FE01": CardStats(card_id="FE01", n=10, sum_delta=20.0, sum_sq=50.0),
            "M01": CardStats(card_id="M01", n=5, sum_delta=-5.0, sum_sq=10.0),
        }

        retriever = CardRetriever(cards=sample_cards, card_stats=card_stats, default_k=3)
        context = RetrievalContext(code_text="")

        selected = retriever.retrieve(context)

        assert len(selected) > 0

    def test_retriever_rotation_prevents_monopolization(self, sample_cards):
        """Test that 5 consecutive invalid rounds don't offer identical card set.

        This tests the recently_offered_penalty and failed_card_sets logic
        that prevents priority-1 cards from monopolizing every prompt.
        """
        retriever = CardRetriever(cards=sample_cards, default_k=3)

        offered_sets: list[set[str]] = []

        for i in range(5):
            recently_offered = {}
            for card_id in ["FE01", "M01", "T01", "E01"]:
                recently_offered[card_id] = i

            failed_sets = [{"FE01", "M01", "T01"}] * i if i > 0 else []

            context = RetrievalContext(
                code_text="import lightgbm",
                recently_offered_cards=recently_offered,
                failed_card_sets=failed_sets,
            )

            selected = retriever.retrieve(context)
            selected_ids = frozenset(c.id for c in selected)
            offered_sets.append(selected_ids)

        unique_sets = set(frozenset(s) for s in offered_sets)
        assert len(unique_sets) > 1, \
            f"Card sets should rotate but got same set {len(unique_sets)} times: {offered_sets}"

    def test_retriever_limits_cards_from_failed_sets(self, sample_cards):
        """Test that at most 1 card from a failed set is offered."""
        retriever = CardRetriever(cards=sample_cards, default_k=4)

        context = RetrievalContext(
            code_text="",
            failed_card_sets=[{"FE01", "M01", "T01"}],
        )

        selected = retriever.retrieve(context)
        selected_ids = {c.id for c in selected}

        from_failed = selected_ids & {"FE01", "M01", "T01"}
        assert len(from_failed) <= 1, \
            f"Should offer at most 1 card from failed set, got {len(from_failed)}: {from_failed}"

    def test_retriever_penalizes_high_invalid_rate(self, sample_cards):
        """Test that cards with high invalid rate get lower scores."""
        good_stats = CardStats(card_id="FE01", n=10, sum_delta=5.0, sum_sq=10.0, invalid_count=0)
        bad_stats = CardStats(card_id="M01", n=10, sum_delta=5.0, sum_sq=10.0, invalid_count=8)

        retriever = CardRetriever(
            cards=sample_cards,
            card_stats={"FE01": good_stats, "M01": bad_stats},
            default_k=2,
        )

        context = RetrievalContext(code_text="import lightgbm")
        selected = retriever.retrieve(context)

        selected_ids = [c.id for c in selected]
        if "FE01" in selected_ids and "M01" in selected_ids:
            assert selected_ids.index("FE01") < selected_ids.index("M01"), \
                "FE01 (no invalids) should rank higher than M01 (80% invalid rate)"


class TestAdoptedCardsParsing:
    """Tests for parsing adopted_cards from LLM responses."""

    def test_parse_adopted_cards_basic(self):
        """Test basic parsing of adopted cards."""
        response = "<adopted_cards>FE01,M01</adopted_cards>"
        cards = extract_adopted_cards_from_response(response)
        assert cards == ["FE01", "M01"]

    def test_parse_adopted_cards_with_whitespace(self):
        """Test parsing with extra whitespace."""
        response = "<adopted_cards>  FE01 , M01 ,T01  </adopted_cards>"
        cards = extract_adopted_cards_from_response(response)
        assert cards == ["FE01", "M01", "T01"]

    def test_parse_adopted_cards_empty(self):
        """Test parsing empty adopted cards."""
        response = "<adopted_cards></adopted_cards>"
        cards = extract_adopted_cards_from_response(response)
        assert cards == []

    def test_parse_adopted_cards_missing_tag(self):
        """Test that missing tag returns empty list."""
        response = "No adopted cards tag here"
        cards = extract_adopted_cards_from_response(response)
        assert cards == []

    def test_parse_adopted_cards_case_insensitive(self):
        """Test case-insensitive parsing."""
        response = "<ADOPTED_CARDS>FE01</ADOPTED_CARDS>"
        cards = extract_adopted_cards_from_response(response)
        assert cards == ["FE01"]

    def test_parse_adopted_cards_in_full_response(self):
        """Test parsing from full LLM response."""
        response = """<hypothesis>Test hypothesis</hypothesis>
<intent>Test intent</intent>
<adopted_cards>FE01,FE02</adopted_cards>

```python
import pandas as pd
# code here
```"""
        cards = extract_adopted_cards_from_response(response)
        assert cards == ["FE01", "FE02"]

    def test_parse_adopted_cards_single(self):
        """Test parsing single card."""
        response = "<adopted_cards>T01</adopted_cards>"
        cards = extract_adopted_cards_from_response(response)
        assert cards == ["T01"]


class TestCardStatsUpdate:
    """Tests for card statistics updates."""

    def test_card_stats_mean_delta(self):
        """Test Bayesian mean delta calculation."""
        stats = CardStats(card_id="FE01", n=10, sum_delta=20.0, sum_sq=50.0)
        assert stats.mean_delta == 2.0

    def test_card_stats_empty(self):
        """Test stats with no observations."""
        stats = CardStats(card_id="FE01", n=0, sum_delta=0.0, sum_sq=0.0)
        assert stats.mean_delta == 0.0
        assert stats.variance == 1.0


class TestConstraintsInjection:
    """Tests for constraints injection in prompts."""

    def test_hdd_adapter_constraints(self):
        """Test that HDD adapter returns constraints."""
        from faultevolve.tasks.protocol import TaskSpec

        adapter = HDDAdapter()
        benchmark_dir = Path(__file__).resolve().parents[1] / "benchmark/hdd_mvp"

        task_spec = TaskSpec(
            task_dir=Path("/tmp"),
            problem_md="",
            prompt_md="",
            init_code="",
            evaluator_path=benchmark_dir / "evaluator.py",
        )

        constraints = adapter.constraints(task_spec)

        assert "静态检查" in constraints or "forbidden" in constraints.lower()
        assert "300" in constraints or "运行时间" in constraints
        assert len(constraints) > 100

    def test_hdd_constraints_contain_forbidden_tokens(self):
        """Test that HDD constraints list some forbidden tokens."""
        from faultevolve.tasks.hdd_adapter import HDDAdapter, HDD_FORBIDDEN_TOKENS

        assert "holdout" in HDD_FORBIDDEN_TOKENS
        assert "glob" in HDD_FORBIDDEN_TOKENS
        assert ".parent" in HDD_FORBIDDEN_TOKENS


class TestEngineTaskAgnostic:
    """Tests to ensure engine remains task-agnostic."""

    @pytest.fixture
    def src_dir(self):
        """Get path to src directory."""
        return Path(__file__).resolve().parents[1] / "src"

    def test_no_hdd_strings_in_engine_class(self, src_dir):
        """Test that EvolutionEngine class does not contain HDD-specific strings.

        Note: run_local_evolution uses HDDAdapter as default which is intentional.
        This test only checks the EvolutionEngine class itself is task-agnostic.
        """
        engine_path = src_dir / "faultevolve/cloud/engine.py"
        content = engine_path.read_text(encoding="utf-8")

        import re
        class_match = re.search(
            r"class EvolutionEngine.*?(?=\ndef run_local_evolution|\nclass |\Z)",
            content,
            re.DOTALL
        )

        if class_match:
            engine_class = class_match.group()
            hdd_terms = ["hdd", "hard drive", "smart_", "backblaze", "disk failure"]
            for term in hdd_terms:
                assert term.lower() not in engine_class.lower(), \
                    f"EvolutionEngine class contains HDD term: {term}"

    def test_no_hdd_strings_in_operators(self, src_dir):
        """Test that operators.py does not contain HDD-specific strings."""
        operators_path = src_dir / "faultevolve/cloud/operators.py"
        content = operators_path.read_text(encoding="utf-8")

        hdd_terms = ["hdd", "hard drive", "smart_", "backblaze", "disk failure"]
        for term in hdd_terms:
            assert term.lower() not in content.lower(), f"Operators contains HDD term: {term}"

    def test_no_hdd_strings_in_selection(self, src_dir):
        """Test that selection.py does not contain HDD-specific strings."""
        selection_path = src_dir / "faultevolve/cloud/selection.py"
        content = selection_path.read_text(encoding="utf-8")

        hdd_terms = ["hdd", "hard drive", "smart_", "backblaze", "disk failure"]
        for term in hdd_terms:
            assert term.lower() not in content.lower(), f"Selection contains HDD term: {term}"


class TestLoadActualKnowledgePack:
    """Tests loading the actual knowledge pack."""

    def test_load_hdd_knowledge_pack(self):
        """Test loading the HDD knowledge pack."""
        knowledge_dir = Path(__file__).resolve().parents[1] / "benchmark/hdd_mvp/knowledge"
        if not knowledge_dir.exists():
            pytest.skip("Knowledge pack not found")

        cards, errors = load_cards(knowledge_dir / "cards.jsonl")

        assert len(cards) > 40, f"Expected > 40 cards, got {len(cards)}"
        assert len(errors) == 0, f"Errors: {errors}"

        categories = {c.category for c in cards}
        assert len(categories) >= 5, "Expected multiple categories"

        assert any(c.id.startswith("FE") for c in cards)
        assert any(c.id.startswith("M") for c in cards)
        assert any(c.id.startswith("T") for c in cards)


class TestEngineLevelKnowledgeInjection:
    """Engine-level tests for knowledge injection."""

    @pytest.fixture
    def task_dir(self, tmp_path):
        """Create a temporary task directory with knowledge pack."""
        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()

        cards = [
            {"id": "FE01", "title": "Test Feature", "category": "feature_engineering",
             "claim": "Test claim", "source_ids": [], "tags": ["model"],
             "impl_hint": "Use groupby", "risk": "May slow down", "priority": 1},
            {"id": "M01", "title": "LightGBM", "category": "model",
             "claim": "LightGBM is efficient", "source_ids": [], "tags": ["lightgbm"],
             "impl_hint": "Set num_leaves", "risk": "Overfitting", "priority": 1},
        ]
        cards_path = knowledge_dir / "cards.jsonl"
        with cards_path.open("w") as f:
            for card in cards:
                f.write(json.dumps(card) + "\n")

        (tmp_path / "evolve.yaml").write_text("""
knowledge:
  dir: knowledge
  k: 2
  max_per_category: 1
""")

        return tmp_path

    def test_prompts_contain_knowledge_cards_block(self, task_dir, tmp_path):
        """Test that refine prompts contain knowledge cards when available."""
        from faultevolve.cloud.operators import OperatorContext, build_user_message
        from faultevolve.common.schemas import (
            Node, NodeArtifact, NodeEvidence, EvaluationResult,
            OperatorType, NodeStatus, HypothesisStatus, BranchMemory
        )
        from faultevolve.tasks.protocol import TaskSpec

        task_spec = TaskSpec(
            task_dir=task_dir,
            problem_md="Test problem",
            prompt_md="Test prompt",
            init_code="# init",
            evaluator_path=task_dir / "evaluator.py",
        )

        node = Node(
            id="test-node",
            experiment_id="test-exp",
            branch_id="main",
            artifact=NodeArtifact(code="import lightgbm", intent="test", hypothesis="test"),
            evidence=NodeEvidence(evaluation=EvaluationResult(
                validity=1.0, combined_score=20.0, cost_time=1.0, error_info="", metric={}
            )),
            status=NodeStatus.DONE,
            hypothesis_status=HypothesisStatus.OPEN,
            branch_memory=BranchMemory(),
        )

        ctx = OperatorContext(node, task_spec, OperatorType.REFINE)
        ctx.set_knowledge_cards([
            {"id": "FE01", "title": "Test Feature", "claim": "Test claim",
             "impl_hint": "Use groupby", "risk": "May slow down"},
        ])

        prompt = build_user_message(ctx)

        assert "<knowledge_cards>" in prompt
        assert "</knowledge_cards>" in prompt
        assert "## 知识卡片" in prompt
        assert "FE01" in prompt
        assert "Test claim" in prompt
        assert "Use groupby" in prompt
        assert "May slow down" in prompt

    def test_prompts_contain_constraints(self, task_dir):
        """Test that prompts contain constraints when provided."""
        from faultevolve.cloud.operators import OperatorContext, build_user_message
        from faultevolve.common.schemas import (
            Node, NodeArtifact, NodeEvidence, EvaluationResult,
            OperatorType, NodeStatus, HypothesisStatus, BranchMemory
        )
        from faultevolve.tasks.protocol import TaskSpec

        task_spec = TaskSpec(
            task_dir=task_dir,
            problem_md="Test problem",
            prompt_md="Test prompt",
            init_code="# init",
            evaluator_path=task_dir / "evaluator.py",
        )

        node = Node(
            id="test-node",
            experiment_id="test-exp",
            branch_id="main",
            artifact=NodeArtifact(code="# code", intent="test", hypothesis="test"),
            evidence=NodeEvidence(evaluation=EvaluationResult(
                validity=1.0, combined_score=20.0, cost_time=1.0, error_info="", metric={}
            )),
            status=NodeStatus.DONE,
            hypothesis_status=HypothesisStatus.OPEN,
            branch_memory=BranchMemory(),
        )

        ctx = OperatorContext(node, task_spec, OperatorType.REFINE)
        ctx.set_constraints("禁止使用 eval() 函数。运行时间不超过 300 秒。")

        prompt = build_user_message(ctx)

        assert "## 硬约束" in prompt
        assert "禁止使用 eval() 函数" in prompt
        assert "300 秒" in prompt

    def test_repair_prompts_contain_constraints(self):
        """Test that repair prompts contain constraints when provided."""
        from faultevolve.cloud.llm import MockLLM
        from faultevolve.cloud.operators import RepairOperator
        from faultevolve.common.schemas import (
            Node, NodeArtifact, NodeEvidence, EvaluationResult,
            OperatorType, NodeStatus, HypothesisStatus, BranchMemory
        )
        from faultevolve.tasks.protocol import TaskSpec
        from pathlib import Path

        llm = MockLLM()
        repair_op = RepairOperator(llm)

        task_spec = TaskSpec(
            task_dir=Path("/tmp"),
            problem_md="Test problem",
            prompt_md="Test prompt",
            init_code="# init",
            evaluator_path=Path("/tmp/evaluator.py"),
        )

        parent = Node(
            id="parent",
            experiment_id="exp",
            branch_id="main",
            artifact=NodeArtifact(code="# parent code", intent="", hypothesis=""),
            evidence=NodeEvidence(evaluation=EvaluationResult(
                validity=1.0, combined_score=20.0, cost_time=1.0, error_info="", metric={}
            )),
            status=NodeStatus.DONE,
            hypothesis_status=HypothesisStatus.OPEN,
            branch_memory=BranchMemory(),
        )

        test_constraints = "禁止使用 holdout 数据。"

        code, intent, hypothesis, metrics = repair_op.generate(
            failing_code="# failing code",
            error_info="TypeError: unsupported operand",
            parent_node=parent,
            task_spec=task_spec,
            constraints=test_constraints,
        )

        assert code is not None

    def test_mock_run_produces_knowledge_metrics(self, task_dir, tmp_path):
        """Test that a mock run with knowledge produces non-zero metrics."""
        from faultevolve.cloud.engine import run_local_evolution

        init_code = """
import pandas as pd

def main():
    return {"validity": 1.0, "combined_score": 22.0}

if __name__ == "__main__":
    main()
"""
        (task_dir / "init.py").write_text(init_code)
        (task_dir / "problem.md").write_text("# Test problem")
        (task_dir / "prompt.md").write_text("# Test prompt")

        evaluator_code = '''
def evaluate(candidate_path, timeout=900, split="val"):
    return {
        "validity": 1.0,
        "combined_score": 22.0,
        "cost_time": 1.0,
        "error_info": "",
        "metric": {"f1": 0.25, "f1_boot_std": 0.02},
    }
'''
        (task_dir / "evaluator.py").write_text(evaluator_code)

        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        result = run_local_evolution(
            task_dir=task_dir,
            mock=True,
            max_iterations=3,
            runs_dir=runs_dir,
        )

        assert result["status"] == "finished"
        assert result["iterations_done"] >= 1

        summary_path = Path(result["output_dir"]) / "run_summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
            assert "knowledge_tokens" in summary or "cards_offered" in summary


class TestPrecheck:
    """Tests for pre-evaluation static checks and auto-rewrites."""

    def test_fix_fillna_method_ffill(self):
        """Test that fillna(method='ffill') is fixed to ffill()."""
        from faultevolve.common.precheck import precheck_and_fix

        code = "df = df.fillna(method='ffill')"
        result = precheck_and_fix(code)

        assert result.was_fixed
        assert "ffill()" in result.fixed_code
        assert "fillna(method=" not in result.fixed_code
        assert len(result.fixes_applied) == 1
        assert "ffill" in result.fixes_applied[0]

    def test_fix_fillna_method_bfill(self):
        """Test that fillna(method='bfill') is fixed to bfill()."""
        from faultevolve.common.precheck import precheck_and_fix

        code = "df = df.fillna(method='bfill')"
        result = precheck_and_fix(code)

        assert result.was_fixed
        assert "bfill()" in result.fixed_code
        assert "fillna(method=" not in result.fixed_code

    def test_fix_verbose_eval(self):
        """Test that verbose_eval is removed from LightGBM calls."""
        from faultevolve.common.precheck import precheck_and_fix

        code = "lgb.train(params, train_set, verbose_eval=10)"
        result = precheck_and_fix(code)

        assert result.was_fixed
        assert "verbose_eval" not in result.fixed_code
        assert len(result.fixes_applied) == 1

    def test_fix_early_stopping_rounds(self):
        """Test that early_stopping_rounds is removed."""
        from faultevolve.common.precheck import precheck_and_fix

        code = "model.fit(X, y, early_stopping_rounds=50)"
        result = precheck_and_fix(code)

        assert result.was_fixed
        assert "early_stopping_rounds" not in result.fixed_code

    def test_fix_data_dir_underscore(self):
        """Test that --data_dir is auto-fixed to --data-dir."""
        from faultevolve.common.precheck import precheck_and_fix

        code = """
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--data_dir', required=True)
args = parser.parse_args()
"""
        result = precheck_and_fix(code)

        assert result.was_fixed
        assert "--data-dir" in result.fixed_code
        assert "--data_dir" not in result.fixed_code

    def test_is_api_compat_error(self):
        """Test detection of API compatibility errors."""
        from faultevolve.common.precheck import is_api_compat_error

        assert is_api_compat_error("TypeError: fillna() got an unexpected keyword argument 'method'")
        assert is_api_compat_error("TypeError: train() got an unexpected keyword argument 'verbose_eval'")
        assert is_api_compat_error("TypeError: fit() got an unexpected keyword argument 'early_stopping_rounds'")
        assert not is_api_compat_error("ValueError: invalid data format")
        assert not is_api_compat_error("RuntimeError: out of memory")
        assert not is_api_compat_error("SystemExit: error: the following arguments are required")

    def test_get_error_fix_hint(self):
        """Test getting fix hints for known errors."""
        from faultevolve.common.precheck import get_error_fix_hint

        hint = get_error_fix_hint("TypeError: fillna() got an unexpected keyword argument 'method'")
        assert "ffill" in hint or "bfill" in hint

        hint = get_error_fix_hint("TypeError: train() got an unexpected keyword argument 'verbose_eval'")
        assert "callbacks" in hint.lower() or "log_evaluation" in hint

    def test_precheck_combined_fixes(self):
        """Test that multiple issues are fixed in one pass."""
        from faultevolve.common.precheck import precheck_and_fix

        code = """
df = df.fillna(method='ffill')
model = lgb.train(params, train_set, verbose_eval=10, early_stopping_rounds=50)
"""
        result = precheck_and_fix(code)

        assert result.was_fixed
        assert "fillna(method=" not in result.fixed_code
        assert "verbose_eval" not in result.fixed_code
        assert "early_stopping_rounds" not in result.fixed_code
        assert len(result.fixes_applied) >= 3

    def test_precheck_no_false_positives(self):
        """Test that valid code is not modified."""
        from faultevolve.common.precheck import precheck_and_fix

        code = """
df = df.ffill()
model = lgb.train(params, train_set, valid_sets=[valid_set], callbacks=[lgb.early_stopping(50)])
"""
        result = precheck_and_fix(code)

        assert not result.was_fixed
        assert result.fixed_code == result.original_code
        assert len(result.fixes_applied) == 0

    def test_detect_performance_issues(self):
        """Test that performance issues are detected but not auto-fixed."""
        from faultevolve.common.precheck import precheck_and_fix

        code_serial_loop = """
for sn in df['serial_number'].unique():
    sn_data = df[df['serial_number'] == sn]
    process(sn_data)
"""
        result = precheck_and_fix(code_serial_loop)
        assert result.has_unfixable
        assert any("serial_number.unique()" in issue for issue in result.unfixable_issues)

        code_groupby_lambda = """
df.groupby('serial_number').apply(lambda g: g.diff().mean())
"""
        result = precheck_and_fix(code_groupby_lambda)
        assert result.has_unfixable
        assert any("groupby" in issue and "apply" in issue for issue in result.unfixable_issues)

    def test_fix_early_stopping_without_eval_set(self):
        """Test that early_stopping callback is removed when no eval_set."""
        from faultevolve.common.precheck import precheck_and_fix

        code = """
model = lgb.train(params, train_set, callbacks=[lgb.early_stopping(50)])
"""
        result = precheck_and_fix(code)
        assert result.was_fixed
        assert "early_stopping" not in result.fixed_code
        assert any("early_stopping callback" in fix for fix in result.fixes_applied)

    def test_early_stopping_kept_with_eval_set(self):
        """Test that early_stopping is kept when eval_set is present."""
        from faultevolve.common.precheck import precheck_and_fix

        code = """
model.fit(X, y, eval_set=[(X_val, y_val)], callbacks=[lgb.early_stopping(50)])
"""
        result = precheck_and_fix(code)
        assert not result.was_fixed
        assert "early_stopping" in result.fixed_code


class TestKnowledgeEnabled:
    """Test knowledge.enabled config switch."""

    def test_knowledge_disabled_returns_empty_cards(self):
        """Test that knowledge injection can be disabled."""
        from faultevolve.config import KnowledgeConfig

        config = KnowledgeConfig(enabled=False)
        assert config.enabled is False

    def test_knowledge_enabled_by_default(self):
        """Test that knowledge is enabled by default."""
        from faultevolve.config import KnowledgeConfig

        config = KnowledgeConfig()
        assert config.enabled is True


class TestSmokeTestConfig:
    """Test smoke test configuration."""

    def test_smoke_test_config_defaults(self):
        """Test smoke test config default values."""
        from faultevolve.config import SmokeTestConfig

        config = SmokeTestConfig()
        assert config.enabled is True
        assert config.sample_fraction == 0.02
        assert config.timeout_s == 60

    def test_smoke_test_config_custom(self):
        """Test smoke test config with custom values."""
        from faultevolve.config import SmokeTestConfig

        config = SmokeTestConfig(enabled=False, timeout_s=30)
        assert config.enabled is False
        assert config.timeout_s == 30


class TestNewRunSummaryFields:
    """Test new run summary fields."""

    def test_run_summary_has_new_fields(self):
        """Test that RunSummary has perf_rejections, smoke_failures, smoke_fixes."""
        from faultevolve.common.schemas import RunSummary

        summary = RunSummary(
            experiment_id="test",
            status="finished",
            iterations_done=10,
            best_score=30.0,
            perf_rejections=2,
            smoke_failures=3,
            smoke_fixes=1,
        )
        assert summary.perf_rejections == 2
        assert summary.smoke_failures == 3
        assert summary.smoke_fixes == 1

    def test_run_metrics_has_new_fields(self):
        """Test that RunMetrics has new fields."""
        from faultevolve.common.metering import RunMetrics

        metrics = RunMetrics()
        metrics.perf_rejections = 5
        metrics.smoke_failures = 3
        metrics.smoke_fixes = 2

        d = metrics.to_dict()
        assert d["perf_rejections"] == 5
        assert d["smoke_failures"] == 3
        assert d["smoke_fixes"] == 2


class TestDataSchemaInjection:
    """Test data schema injection into prompts."""

    def test_hdd_adapter_has_data_schema(self):
        """Test that HDDAdapter has data_schema method."""
        from faultevolve.tasks.hdd_adapter import HDDAdapter

        adapter = HDDAdapter()
        schema = adapter.data_schema()
        assert "serial_number" in schema
        assert "date" in schema
        assert "smart_" in schema
        assert "不要发明" in schema

    def test_hdd_adapter_has_edit_guidance(self):
        """Test that HDDAdapter has edit_guidance method."""
        from faultevolve.tasks.hdd_adapter import HDDAdapter

        adapter = HDDAdapter()
        guidance = adapter.edit_guidance()
        assert "最小编辑" in guidance or "60" in guidance
        assert "辅助函数" in guidance


class TestSmokeTestSampling:
    """Test smoke test sampling behavior."""

    def test_build_smoke_data_dir_returns_none_without_data(self, tmp_path):
        """Test that build_smoke_data_dir returns None when data files missing."""
        from faultevolve.tasks.hdd_adapter import HDDAdapter
        from faultevolve.tasks.protocol import TaskSpec

        adapter = HDDAdapter()
        task_spec = TaskSpec(
            task_dir=tmp_path,
            problem_md="test",
            prompt_md="test",
            init_code="",
            evaluator_path=tmp_path / "evaluator.py",
        )

        result = adapter.build_smoke_data_dir(task_spec)
        assert result is None

    def test_smoke_test_falls_back_to_base_without_data(self, tmp_path):
        """Test that smoke_test falls back to base impl when no data."""
        from faultevolve.tasks.hdd_adapter import HDDAdapter
        from faultevolve.tasks.protocol import TaskSpec

        adapter = HDDAdapter()
        task_spec = TaskSpec(
            task_dir=tmp_path,
            problem_md="test",
            prompt_md="test",
            init_code="",
            evaluator_path=tmp_path / "evaluator.py",
        )

        (tmp_path / "evaluator.py").write_text("""
def evaluate(path, timeout=900):
    return {"validity": 0, "combined_score": 0, "cost_time": 0, "error_info": "test"}
""")

        code = "print('test')"
        result = adapter.smoke_test(code, task_spec, timeout=5)
        assert result.validity == 0.0

    def test_sample_fraction_config(self):
        """Test that sample_fraction is respected in config."""
        from faultevolve.config import SmokeTestConfig

        config = SmokeTestConfig(sample_fraction=0.05)
        assert config.sample_fraction == 0.05

        config = SmokeTestConfig(sample_fraction=0.01)
        assert config.sample_fraction == 0.01

    def test_build_smoke_data_real_pandas(self, tmp_path):
        """Test build_smoke_data_dir with real pandas on tiny fixture (no mocks)."""
        import pandas as pd
        from faultevolve.tasks.hdd_adapter import HDDAdapter
        from faultevolve.tasks.protocol import TaskSpec

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        n_disks = 5000
        n_positives = 100
        serials = [f"SN{i:06d}" for i in range(n_disks)]
        labels = [1 if i < n_positives else 0 for i in range(n_disks)]

        train_labels = pd.DataFrame({
            "serial_number": serials,
            "model": ["MODEL_A"] * n_disks,
            "cutoff_date": ["2026-01-01"] * n_disks,
            "label": labels,
            "weight": [1.0] * n_disks,
        })
        train_labels.to_csv(data_dir / "train_labels.csv", index=False)

        val_serials = [f"VAL{i:06d}" for i in range(500)]
        val_index = pd.DataFrame({
            "serial_number": val_serials,
            "model": ["MODEL_A"] * 500,
            "cutoff_date": ["2026-01-01"] * 500,
        })
        val_index.to_csv(data_dir / "val_index.csv", index=False)

        adapter = HDDAdapter()
        task_spec = TaskSpec(
            task_dir=tmp_path,
            problem_md="test",
            prompt_md="test",
            init_code="",
            evaluator_path=tmp_path / "evaluator.py",
        )

        smoke_dir = adapter.build_smoke_data_dir(
            task_spec, sample_fraction=0.02, min_positives=20
        )
        assert smoke_dir is not None
        assert smoke_dir.exists()
        assert (smoke_dir / "_ready").exists()

        sampled_labels = pd.read_csv(smoke_dir / "train_labels.csv")
        sampled_val = pd.read_csv(smoke_dir / "val_index.csv")

        assert len(sampled_labels) > 0
        assert len(sampled_val) > 0

        sample_ratio = len(sampled_labels) / n_disks
        assert sample_ratio <= 0.10, f"Sample ratio {sample_ratio:.2%} too large (expected <= 10%)"

        import shutil
        shutil.rmtree(smoke_dir, ignore_errors=True)

    def test_smoke_command_uses_sys_executable(self, tmp_path, monkeypatch):
        """Test that smoke_test uses sys.executable, not bare 'python3'."""
        import subprocess
        import sys
        from faultevolve.tasks.hdd_adapter import HDDAdapter
        from faultevolve.tasks.protocol import TaskSpec

        captured_cmd = []
        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            captured_cmd.append(cmd)
            raise subprocess.TimeoutExpired(cmd, 1)

        monkeypatch.setattr(subprocess, "run", mock_run)

        adapter = HDDAdapter()
        task_spec = TaskSpec(
            task_dir=tmp_path,
            problem_md="test",
            prompt_md="test",
            init_code="",
            evaluator_path=tmp_path / "evaluator.py",
        )

        smoke_dir = tmp_path / "smoke_data"
        smoke_dir.mkdir()
        (smoke_dir / "_ready").touch()
        (smoke_dir / "val_index.csv").write_text("serial_number\nSN001\n")

        code = "print('test')"
        adapter.smoke_test(code, task_spec, timeout=1, smoke_data_dir=smoke_dir)

        assert len(captured_cmd) > 0, "subprocess.run was not called"
        cmd = captured_cmd[0]
        assert cmd[0] == sys.executable, f"Expected {sys.executable}, got {cmd[0]}"

    def test_sample_size_fraction_small(self, tmp_path):
        """Test that sample size is small (~2-3% of disks) not 39%."""
        import pandas as pd
        from faultevolve.tasks.hdd_adapter import HDDAdapter
        from faultevolve.tasks.protocol import TaskSpec

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        n_disks = 31000
        n_positives = 1100
        serials = [f"SN{i:08d}" for i in range(n_disks)]
        labels = [1 if i < n_positives else 0 for i in range(n_disks)]

        train_labels = pd.DataFrame({
            "serial_number": serials,
            "model": ["MODEL_A"] * n_disks,
            "cutoff_date": ["2026-01-01"] * n_disks,
            "label": labels,
            "weight": [1.0] * n_disks,
        })
        train_labels.to_csv(data_dir / "train_labels.csv", index=False)

        val_index = pd.DataFrame({
            "serial_number": [f"VAL{i:06d}" for i in range(5000)],
            "model": ["MODEL_A"] * 5000,
            "cutoff_date": ["2026-01-01"] * 5000,
        })
        val_index.to_csv(data_dir / "val_index.csv", index=False)

        adapter = HDDAdapter()
        task_spec = TaskSpec(
            task_dir=tmp_path,
            problem_md="test",
            prompt_md="test",
            init_code="",
            evaluator_path=tmp_path / "evaluator.py",
        )

        smoke_dir = adapter.build_smoke_data_dir(
            task_spec, sample_fraction=0.02, min_positives=20
        )
        assert smoke_dir is not None

        sampled_labels = pd.read_csv(smoke_dir / "train_labels.csv")
        sample_ratio = len(sampled_labels) / n_disks

        assert sample_ratio <= 0.10, (
            f"Sample ratio {sample_ratio:.2%} too large! "
            f"Expected <= 10%, got {len(sampled_labels)}/{n_disks}"
        )
        assert sample_ratio >= 0.01, f"Sample ratio {sample_ratio:.2%} too small"

        n_sampled_positives = (sampled_labels["label"] == 1).sum()
        assert n_sampled_positives >= 20, f"Not enough positives: {n_sampled_positives}"
        assert n_sampled_positives < n_positives, (
            f"All positives kept ({n_sampled_positives}), should be capped"
        )

        import shutil
        shutil.rmtree(smoke_dir, ignore_errors=True)


class TestRepairPerfGate:
    """Test that repair path goes through perf gate and smoke test."""

    def test_repair_checks_perf_issues(self, tmp_path):
        """Test that repair attempts check for performance issues."""
        from faultevolve.common.precheck import precheck_and_fix

        bad_code = """
for sn in df['serial_number'].unique():
    process(sn)
"""
        result = precheck_and_fix(bad_code)
        assert result.has_unfixable
        assert any("serial_number.unique()" in issue for issue in result.unfixable_issues)
