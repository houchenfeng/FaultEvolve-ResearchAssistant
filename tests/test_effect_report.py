"""Convergence and automation figures come from the run's own records, never from an LLM."""

import json

from faultevolve.effect_report import automation_report, convergence_report, program_complexity


def event(kind, ts, **payload):
    return {"type": kind, "ts": f"2026-10-17T11:{ts}+00:00", "payload": payload}


EVENTS = [
    event("init_evaluated", "00:00"), event("attempt_started", "00:05"),
    event("iteration_complete", "02:05", valid=True, score=36.0),
    event("attempt_started", "02:06"),
    event("iteration_complete", "04:06", valid=False, score=None),
    event("attempt_started", "04:07"),
    event("iteration_complete", "06:07", valid=True, score=34.0),  # worse than the best so far
]
LEDGER = {"elapsed_seconds": 90.0, "stop_reason": "trial_budget_exhausted", "trials": [
    {"trial_number": 1, "evaluation": {"score": 30.0}}, {"trial_number": 2, "evaluation": {"score": None}},
    {"trial_number": 3, "evaluation": {"score": 41.0}}, {"trial_number": 4, "evaluation": {"score": 39.0}}]}


def test_best_so_far_never_decreases_and_invalid_rounds_are_skipped(tmp_path):
    summary = {"initial_score": 22.8, "iterations_done": 3, "rounds_to_target": 1, "time_to_target_s": 125.0,
               "tokens_to_target": 100, "stop_reason": "max_iterations"}
    result = convergence_report(tmp_path, summary, LEDGER, 33.7, EVENTS)
    assert [p["best_so_far"] for p in result["evolution_curve"]] == [36.0, 36.0]
    assert result["evolution_curve"][0]["elapsed_s"] == 125.0
    assert result["target_reached"] is True and result["rounds_to_target"] == 1
    assert [p["best_so_far"] for p in result["hpo_curve"]] == [30.0, 30.0, 41.0, 41.0]
    assert result["hpo_best_trial"] == 3


def test_target_state_is_unknown_without_a_target_and_false_when_missed(tmp_path):
    assert convergence_report(tmp_path, {}, None, None, [])["target_reached"] is None
    assert convergence_report(tmp_path, {"initial_score": 1.0}, None, 50.0, [])["target_reached"] is False


def test_resumes_and_interruptions_count_as_manual_intervention():
    clean = automation_report({}, LEDGER, EVENTS, True)
    assert clean["total_steps"] == 3 + 3 + 4 and clean["automatic_coverage"] == 1.0 and clean["end_to_end_unattended"]
    touched = automation_report({"smoke_fixes": 2, "repair_successes": 1}, LEDGER,
                                EVENTS + [event("run_interrupted", "07:00"), event("run_resumed", "08:00")], True)
    assert touched["manual_interventions"] == 2 and not touched["end_to_end_unattended"]
    assert touched["automatic_coverage"] == round(1 - 2 / 10, 4) and touched["self_recovered_failures"] == 3
    assert automation_report({}, None, EVENTS, False)["stages"] == 2


def test_parameter_estimate_resolves_function_defaults_and_declines_unknown_models():
    code = ("import lightgbm as lgb\nfrom sklearn.model_selection import StratifiedKFold\n"
            "def fit(n_splits=3):\n    p = dict(n_estimators=10, num_leaves=4)\n"
            "    StratifiedKFold(n_splits=n_splits)\n    lgb.LGBMClassifier(**p)\n")
    assert program_complexity(code)["estimated_parameters"] == 10 * (3 * 3 + 4) * 3
    forest = program_complexity("from sklearn.ensemble import RandomForestClassifier\nRandomForestClassifier(n_estimators=5)")
    assert forest["estimated_parameters"] is None
    assert json.dumps(forest)  # report stays serialisable


def test_parameter_estimate_uses_expanded_model_dict_instead_of_library_defaults():
    code = ("import lightgbm as lgb\nfrom sklearn.model_selection import StratifiedKFold\n"
            "SEED=7\nN_FOLDS=3\nPARAMS={'n_estimators':600,'num_leaves':16,'random_state':SEED}\n"
            "StratifiedKFold(n_splits=N_FOLDS)\nlgb.LGBMClassifier(**PARAMS)\n")
    assert program_complexity(code)["estimated_parameters"] == 600 * (4 * 16 - 3) * 3
    unknown = "import lightgbm as lgb\nlgb.LGBMClassifier(n_estimators=unknown_rounds)"
    assert program_complexity(unknown)["estimated_parameters"] is None
