from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_search import run  # noqa: E402
from search_engine import EvaluationResult, SearchEngine  # noqa: E402


def load_example_spec() -> dict:
    return json.loads((ROOT / "examples" / "experiment-spec.json").read_text(encoding="utf-8"))


class SearchEngineTest(unittest.TestCase):
    def test_default_barrier_blocks_parameter_search(self) -> None:
        engine = SearchEngine(load_example_spec())
        first = engine.reserve_next(0.0)
        second = engine.reserve_next(0.0)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertEqual(0, first.depth)
        self.assertEqual(0, second.depth)
        self.assertIsNone(engine.reserve_next(0.0))

        engine.record_result(first.candidate_id, EvaluationResult(True, 0.70, [0.70], 0.01, True))
        self.assertIsNone(engine.reserve_next(0.0))
        engine.record_result(second.candidate_id, EvaluationResult(True, 0.68, [0.68], 0.01, True))

        child = engine.reserve_next(0.0)
        self.assertIsNotNone(child)
        assert child is not None
        self.assertGreater(child.depth, 0)
        self.assertTrue(engine.default_barrier_open)

    def test_canonical_candidate_identity_deduplicates(self) -> None:
        engine = SearchEngine(load_example_spec())
        route_id = engine.route_order[0]
        root = engine.candidates[engine.root_ids[route_id]]
        children = engine._possible_children(root)
        duplicate = engine._make_candidate(
            route_id,
            root.candidate_id,
            dict(children[0].parameters),
            children[0].changed_parameter,
            children[0].depth,
            root.backprop_path,
        )
        self.assertEqual(children[0].candidate_id, duplicate.candidate_id)

    def test_invalid_trial_budget_is_rejected(self) -> None:
        spec = copy.deepcopy(load_example_spec())
        spec["budgets"]["max_trials"] = 1
        with self.assertRaises(ValueError):
            SearchEngine(spec)

    def test_virtual_visits_reserve_distinct_candidates(self) -> None:
        engine = SearchEngine(load_example_spec())
        defaults = [engine.reserve_next(0.0), engine.reserve_next(0.0)]
        for index, candidate in enumerate(defaults):
            assert candidate is not None
            engine.record_result(
                candidate.candidate_id,
                EvaluationResult(True, 0.70 - index * 0.01, [0.70 - index * 0.01], 0.01, True),
            )

        first = engine.reserve_next(0.0)
        second = engine.reserve_next(0.0)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertNotEqual(first.candidate_id, second.candidate_id)
        self.assertGreater(engine.route_virtual_visits[first.route_id], 0)

    def test_end_to_end_runner_executes_holdout(self) -> None:
        spec = load_example_spec()
        python = sys.executable
        spec["evaluation"]["command"][0] = python
        spec["holdout"]["command"][0] = python
        with tempfile.TemporaryDirectory() as temporary:
            temp_path = Path(temporary)
            spec_path = temp_path / "experiment-spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
            evaluator = temp_path / "toy_evaluator.py"
            evaluator.write_text((ROOT / "examples" / "toy_evaluator.py").read_text(encoding="utf-8"), encoding="utf-8")
            ledger = run(spec_path, temp_path / "output")

            self.assertTrue(ledger["default_barrier_open"])
            self.assertEqual([0, 0], [trial["depth"] for trial in ledger["trials"][:2]])
            self.assertIsNotNone(ledger["best_candidate"])
            self.assertIsNotNone(ledger["holdout"])
            self.assertTrue(ledger["holdout"]["accepted"])
            self.assertTrue((temp_path / "output" / "ledger.json").exists())


if __name__ == "__main__":
    unittest.main()
