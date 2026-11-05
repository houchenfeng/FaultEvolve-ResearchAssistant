"""Feedback rendering tests."""

from pathlib import Path

from faultevolve.cloud.operators import OperatorContext, build_user_message
from faultevolve.common.schemas import EvaluationResult, Node, NodeArtifact, NodeEvidence, OperatorType
from faultevolve.config import FeedbackConfig
from faultevolve.optimization.feedback import build_feedback, render_feedback
from faultevolve.tasks.protocol import TaskSpec


def test_f1_analysis_not_computed_text():
    cfg = FeedbackConfig()
    parent = Node(
        id="p",
        experiment_id="e",
        branch_id="b",
        depth=0,
        operator=OperatorType.INIT,
        artifact=NodeArtifact(code="x=1"),
        evidence=NodeEvidence(evaluation=EvaluationResult(validity=1, combined_score=1, cost_time=0)),
    )
    bundle = build_feedback(parent, parent, dev_preds=None, config=cfg)
    text = render_feedback(bundle, max_chars=2000)
    assert "错例画像未计算" in text


def test_f6_golden_user_message_unchanged_when_feedback_off():
    golden = Path("tests/fixtures/autotune/user_message_golden.txt").read_text(encoding="utf-8")
    task_spec = TaskSpec(
        task_dir=Path("tests/fixtures/toy_task"),
        problem_md="p",
        prompt_md="sys",
        init_code="x=1",
        evaluator_path=Path("tests/fixtures/toy_task/evaluator.py"),
    )
    node = Node(
        id="n1",
        experiment_id="e1",
        parent_id="root",
        branch_id="b1",
        depth=1,
        operator=OperatorType.REFINE,
        artifact=NodeArtifact(code="print(1)"),
        evidence=NodeEvidence(
            evaluation=EvaluationResult(validity=1.0, combined_score=10.0, cost_time=1.0, metric={"f1_p10": 0.5})
        ),
    )
    ctx = OperatorContext(node, task_spec, OperatorType.REFINE)
    assert build_user_message(ctx) == golden
