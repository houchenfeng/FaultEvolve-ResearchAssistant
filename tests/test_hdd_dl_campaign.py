"""Behavioral tests for honest comparisons, immutable candidates and train-only features."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


controller = module("hdd_dl_control", "experiments/hdd_dl/controller.py")


def test_backend_quota_rotates_after_seeds_and_can_be_disabled():
    seeds = [controller.DEFAULT] * 6
    assert controller.backend_slot(5, seeds, True) is None
    assert [controller.backend_slot(i, seeds, True) for i in range(6, 12)] == list(controller.BACKENDS) * 2
    assert controller.backend_slot(12, seeds, False) is None


@pytest.mark.parametrize("backend", controller.BACKENDS)
def test_backend_quota_selects_local_parent_and_survives_deduplication(backend):
    configs = [controller.constrain_backend(controller.DEFAULT, b) for b in controller.BACKENDS]
    rows = [{"trial": i, "config": c, "result": {"validity": 1, "combined_score": 100 - i}}
            for i, c in enumerate(configs)]
    config, parent, _ = controller.propose(9, rows, backend=backend)
    assert parent == controller.BACKENDS.index(backend)
    assert controller.backend_key(config) == backend
    repeated = controller.constrain_backend(controller.DEFAULT, backend)
    fresh, replaced = controller.unseen_config(repeated, rows, 9, ["mlp", "tcn"], backend)
    assert replaced and controller.backend_key(fresh) == backend
    assert fresh not in configs


def test_inactive_embedding_does_not_create_fake_novel_candidate():
    original = {**controller.DEFAULT, "tabm_embedding": "periodic"}
    canonical = controller.canonical_config(original)
    assert canonical["tabm_embedding"] == "none"
    assert original["tabm_embedding"] == "periodic"
    candidate, replaced = controller.unseen_config(original, [{"config": controller.DEFAULT}], 10, ["mlp", "tcn"])
    assert replaced and candidate != controller.DEFAULT
    if candidate["tabm_members"] == 0:
        assert candidate["tabm_embedding"] == "none"


def test_backend_seeds_keep_reference_and_guarantee_tested_tabm_starts():
    seeds = controller.backend_seeds([controller.DEFAULT])
    assert seeds[0] == controller.DEFAULT
    assert {(c["tabm_members"], c["tabm_embedding"]) for c in seeds} == {(0, "none"), (8, "none"), (8, "periodic")}
    assert all(c["train_seconds"] == 240 for c in seeds)
    assert controller.backend_seeds(seeds) == seeds
    assert {c["replicas"] for c in seeds if c["share_fold_tree"]} == {1, 3}
    assert all(not c["share_fold_tree"] or c["share_fold_preprocessing"] for c in seeds)


def test_search_proposals_keep_backend_choices_valid_and_reachable():
    configs = [controller.propose(i, [])[0] for i in range(8, 512)]
    assert any(c["tabm_members"] == 8 for c in configs)
    assert all(c["tabm_members"] in [0, 8] for c in configs)
    assert all(c["tabm_members"] or c["tabm_embedding"] == "none" for c in configs)


@pytest.mark.parametrize("mode,scale", [("maxabs", 1000), ("percentile99", 2)])
def test_sequence_scale_excludes_validation_and_query_preserves_masks(monkeypatch, mode, scale):
    pytest.importorskip("torch")
    import numpy as np
    c = module("hdd_sequence_scale", "experiments/hdd_dl/candidate.py")
    seq = np.ones((101, 2, 14), dtype=np.float32)
    seq[:, 0] = 2
    seq[0, 0, 0] = 1000
    seq[100, 0] = 1e6
    seq[1, 1, 0] = 0
    query = np.full((2, 2, 14), 1e8, dtype=np.float32)
    query[:, 1] = 1
    originals = seq.copy(), query.copy()
    a, b = c.normalize_sequences(seq, query, np.arange(100), mode)
    np.testing.assert_allclose(a[:, 0], seq[:, 0] / scale)
    np.testing.assert_allclose(b[:, 0], query[:, 0] / scale)
    np.testing.assert_array_equal(a[:, 1], seq[:, 1])
    np.testing.assert_array_equal(b[:, 1], query[:, 1])
    np.testing.assert_array_equal(seq, originals[0])
    np.testing.assert_array_equal(query, originals[1])
    assert a.dtype == np.float32 and b.dtype == np.float32
    with pytest.raises(ValueError, match="sequence_normalization"):
        c.normalize_sequences(seq, query, np.arange(100), "invalid")


def test_memberwise_loss_and_probability_average_follow_ensemble_contract():
    torch = pytest.importorskip("torch")
    c = module("hdd_member_loss", "experiments/hdd_dl/candidate.py")
    z = torch.tensor([[3., -1.], [-2., 0.5]], requires_grad=True)
    y, w, pos = torch.tensor([1., 0.]), torch.tensor([2., 0.5]), torch.tensor(3.)
    actual = c.training_loss(z, y, w, pos)
    expected = torch.stack([(torch.nn.functional.binary_cross_entropy_with_logits(
        z[:, i], y, pos_weight=pos, reduction="none") * w).mean() for i in range(2)]).mean()
    torch.testing.assert_close(actual, expected)
    wrong = (torch.nn.functional.binary_cross_entropy_with_logits(
        z.mean(1), y, pos_weight=pos, reduction="none") * w).mean()
    assert not torch.isclose(actual, wrong)
    torch.testing.assert_close(c.prediction_probability(z), torch.sigmoid(z).mean(1))
    assert not torch.allclose(c.prediction_probability(z), torch.sigmoid(z.mean(1)))
    actual.backward()
    assert torch.isfinite(z.grad).all() and (z.grad.abs().sum(0) > 0).all()


@pytest.mark.parametrize("family", ["mlp", "tcn"])
@pytest.mark.parametrize("members", [8, 16])
@pytest.mark.parametrize("embedding", ["none", "periodic"])
def test_official_tabm_backend_trains_and_returns_entity_probabilities(family, members, embedding):
    torch = pytest.importorskip("torch")
    pytest.importorskip("tabm")
    if not torch.cuda.is_available():
        pytest.skip("GPU candidate")
    import numpy as np
    c = module("hdd_tabm", "experiments/hdd_dl/candidate.py")
    rng = np.random.default_rng(17)
    tab = rng.normal(size=(80, 6)).astype("float32")
    seq = rng.normal(size=(80, 4, 14)).astype("float32")
    y = np.tile([0, 1], 40).astype("float32")
    cfg = {**controller.DEFAULT, "family": family, "tabm_members": members,
           "tabm_embedding": embedding,
           "depth": 2, "width": 16, "epochs": 2, "tree_blend": 0.25,
           "focal_gamma": 1., "ranking_weight": 0.1}
    model = c.Network(6, 4, cfg)
    assert model(torch.from_numpy(tab[:3]), torch.from_numpy(seq[:3])).shape == (3, members)
    q, v = c.fit_one(tab, seq, y, np.ones(80), tab[:7], seq[:7], cfg, np.arange(60), np.arange(60, 80))
    assert q.shape == (7,) and v.shape == (20,)
    assert np.isfinite(q).all() and np.isfinite(v).all()
    assert ((q > 0) & (q < 1)).all()


def test_logit_fusion_handles_extreme_probabilities_without_mutation():
    pytest.importorskip("torch")
    import numpy as np
    c = module("hdd_fusion", "experiments/hdd_dl/candidate.py")
    a = np.array([0., 1., 0., 1., 0.5])
    b = np.array([1., 0., 0., 1., 0.5])
    originals = (a.copy(), b.copy())
    result = c.blend_predictions(a, b, 0.5, "logit")
    assert np.isfinite(result).all() and ((result > 0) & (result < 1)).all()
    np.testing.assert_allclose(result[[0, 1, 4]], 0.5, atol=1e-9)
    np.testing.assert_array_equal(a, originals[0])
    np.testing.assert_array_equal(b, originals[1])
    with pytest.raises(ValueError, match="fusion_mode"):
        c.blend_predictions(a, b, 0.5, "unknown")


def test_bootstrap_threshold_is_reproducible_and_preserves_rng_and_inputs():
    pytest.importorskip("torch")
    import numpy as np
    c = module("hdd_bootstrap", "experiments/hdd_dl/candidate.py")
    y = np.tile([0., 0., 0., 1.], 20)
    p = np.linspace(0.01, 0.99, len(y))
    w = np.linspace(0.5, 2., len(y))
    originals = [a.copy() for a in (y, p, w)]
    cfg = {"threshold_estimator": "bootstrap_median", "seed": 17}
    np.random.seed(23)
    expected = np.random.random(5)
    np.random.seed(23)
    cut = c.calibration_threshold(y, p, w, cfg)
    assert cut == c.calibration_threshold(y, p, w, cfg)
    assert cut in p
    np.testing.assert_array_equal(np.random.random(5), expected)
    for actual, original in zip((y, p, w), originals):
        np.testing.assert_array_equal(actual, original)
    assert c.calibration_threshold(y, p, w, {}) == c.threshold(y, p, w)
    with pytest.raises(ValueError):
        c.calibration_threshold(y, p, w, {"threshold_estimator": "invalid"})


def test_bootstrap_threshold_preserves_classes_and_entity_weights(monkeypatch):
    pytest.importorskip("torch")
    import numpy as np
    c = module("hdd_bootstrap_weights", "experiments/hdd_dl/candidate.py")
    y = np.array([0., 0., 0., 1.])
    p = np.array([0.1, 0.2, 0.3, 0.4])
    w = p * 10
    calls = []
    def check(yy, pp, ww):
        assert yy.sum() == 1 and len(yy) == 4
        np.testing.assert_allclose(ww, pp * 10)
        calls.append(1)
        return 0.4
    monkeypatch.setattr(c, "threshold", check)
    assert c.calibration_threshold(y, p, w, {
        "threshold_estimator": "bootstrap_median", "seed": 17}) == 0.4
    assert len(calls) == 31


def test_sequence_deltas_respect_calendar_gaps_and_resets():
    pytest.importorskip("torch")
    import numpy as np
    c = module("hdd_sequence_deltas", "experiments/hdd_dl/candidate.py")
    seq = np.array([[[2., 5., 0., 9., 4.], [1., 1., 0., 1., 1.]]], dtype="float32")
    before = seq.copy()
    actual = c.append_sequence_deltas(seq)
    np.testing.assert_array_equal(seq, before)
    np.testing.assert_array_equal(actual[:, :2], seq)
    np.testing.assert_array_equal(actual[0, 2], [0., 3., 0., 0., -5.])
    np.testing.assert_array_equal(actual[0, 3], [0., 1., 0., 0., 1.])
    assert np.isfinite(actual).all()


def test_parameter_average_is_detached_and_does_not_change_training_model():
    torch = pytest.importorskip("torch")
    c = module("hdd_ema", "experiments/hdd_dl/candidate.py")
    model, average = torch.nn.Linear(2, 1), torch.nn.Linear(2, 1)
    with torch.no_grad():
        model.weight.fill_(4.)
        model.bias.fill_(2.)
        average.weight.fill_(2.)
        average.bias.fill_(0.)
    c.update_average(average, model, 0.75)
    torch.testing.assert_close(average.weight, torch.full_like(average.weight, 2.5))
    torch.testing.assert_close(average.bias, torch.full_like(average.bias, 0.5))
    torch.testing.assert_close(model.weight, torch.full_like(model.weight, 4.))
    assert average.weight.grad is None and model.weight.grad is None


def result(value=0.5):
    return {"validity": 1, "combined_score": 30,
            "metric": {k: value for k in controller.HIGHER + controller.LOWER}}


def test_equal_is_not_strictly_better():
    assert not controller.comparison(result(), result())["all_predictive_strictly_better"]


def test_missing_or_nonfinite_metric_cannot_pass():
    candidate, base = result(0.8), result()
    candidate["metric"].pop("auprc")
    candidate["metric"]["recall"] = float("nan")
    comparison = controller.comparison(candidate, base)
    assert not comparison["all_predictive_strictly_better"]
    assert not comparison["metrics"]["recall"]["better"]
    assert not comparison["metrics"]["auprc"]["better"]


def test_prediction_win_does_not_hide_runtime_regression():
    candidate, base = result(0.8), result()
    candidate["combined_score"] = 40
    for key in controller.LOWER:
        candidate["metric"][key] = 0.1
    candidate["metric"]["run_time_s"] = 100
    comparison = controller.comparison(candidate, base)
    assert comparison["all_predictive_strictly_better"]
    assert not comparison["all_including_resources_strictly_better"]


def test_render_preserves_frozen_evaluator_constraints():
    evaluator = module("hdd_eval_static", "benchmark/hdd_mvp/evaluator.py")
    template = (ROOT / "experiments/hdd_dl/candidate.py").read_text(encoding="utf-8")
    code = controller.render(template, controller.DEFAULT)
    compile(code, "candidate.py", "exec")
    assert evaluator.static_check(code) == ""
    assert "CONFIG = " + repr(controller.DEFAULT) in code


def test_knowledge_injection_changes_architecture_and_has_provenance():
    mlp, _, mlp_cards = controller.propose(0, [])
    tcn, _, tcn_cards = controller.propose(1, [])
    assert mlp["family"] == "mlp"
    assert tcn["family"] == "tcn"
    assert "DL-TAB-01" in mlp_cards
    assert "DL-SEQ-01" in tcn_cards


def test_invalid_candidate_never_becomes_parent():
    invalid = {"trial": 3, "result": {"validity": 0, "combined_score": 100}}
    _, parent, _ = controller.propose(5, [invalid])
    assert parent is None


def test_loaded_knowledge_actions_control_seed_architecture():
    cards = [{"id": "custom-temporal", "type": "paper_prior", "action": {"family": "tcn"}}]
    config, _, used = controller.propose(0, [], cards)
    assert config["family"] == "tcn"
    assert used == ["custom-temporal"]


def test_nas_disconnect_prevents_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(controller.subprocess, "check_output", lambda *a, **k: "xfs\n")
    output = tmp_path / "faultevolve-dl" / "runs" / "new"
    with pytest.raises(RuntimeError, match="mount identity"):
        controller.guard(tmp_path, output)
    assert not output.exists()


def test_local_disk_floor_prevents_dispatch(tmp_path, monkeypatch):
    from collections import namedtuple
    monkeypatch.setattr(controller.subprocess, "check_output",
                        lambda command, **k: "cifs\n" if command[-1] == "FSTYPE"
                        else "//10.62.192.79/public/hcf_data\n")
    usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(controller.shutil, "disk_usage", lambda p: usage(100, 90, 10))
    with pytest.raises(RuntimeError, match="Local free"):
        controller.guard(tmp_path, tmp_path / "faultevolve-dl/runs/test")


def test_output_cannot_escape_new_project(tmp_path, monkeypatch):
    monkeypatch.setattr(controller.subprocess, "check_output",
                        lambda command, **k: "cifs\n" if command[-1] == "FSTYPE"
                        else "//10.62.192.79/public/hcf_data\n")
    with pytest.raises(ValueError):
        controller.guard(tmp_path, tmp_path / "historical-runs")


def test_calendar_gaps_and_missing_values_have_distinct_masks():
    pytest.importorskip("torch")
    import numpy as np
    import pandas as pd
    candidate = module("hdd_dl_candidate", "experiments/hdd_dl/candidate.py")
    history = pd.DataFrame({
        "serial_number": ["a", "a"], "date": ["2024-01-01", "2024-01-03"],
        "smart_5_raw": [0.0, np.nan]})
    index = pd.DataFrame({"serial_number": ["a"], "model": ["ST"],
                          "cutoff_date": ["2024-01-03"]})
    tab, seq = candidate.features(history, index, ["smart_5_raw"])
    assert seq.shape == (1, 2, 14)
    assert seq[0, 1, 11] == 1
    assert seq[0, 1, 12] == 0
    assert seq[0, 1, 13] == 0
    assert np.isfinite(tab).all()


def test_tab_validity_distinguishes_undefined_std_from_observed_zero():
    pytest.importorskip("torch")
    import numpy as np
    import pandas as pd
    c = module("hdd_tab_validity", "experiments/hdd_dl/candidate.py")
    history = pd.DataFrame({"serial_number": ["a", "b", "b"],
        "date": ["2024-01-03", "2024-01-02", "2024-01-03"],
        "smart_5_raw": [0., 0., 0.]})
    index = pd.DataFrame({"serial_number": ["b", "a", "missing"],
        "model": ["ST"] * 3, "cutoff_date": ["2024-01-03"] * 3})
    base, seq = c.features(history, index, ["smart_5_raw"])
    c.CONFIG["tab_missing_indicators"] = True
    enhanced, new_seq = c.features(history, index, ["smart_5_raw"])
    np.testing.assert_array_equal(base[:, :6], enhanced[:, :6])
    np.testing.assert_array_equal(base[:, 6:], enhanced[:, 12:])
    np.testing.assert_array_equal(seq, new_seq)
    np.testing.assert_array_equal(enhanced[:, 8], [1., 0., 0.])
    np.testing.assert_array_equal(enhanced[2, 6:12], np.zeros(6))
    assert np.isfinite(enhanced).all()


def test_window_contrasts_are_entity_local_and_leave_sequence_unchanged():
    pytest.importorskip("torch")
    import numpy as np
    import pandas as pd
    c = module("hdd_window_contrasts", "experiments/hdd_dl/candidate.py")
    history = pd.DataFrame({"serial_number": ["a", "a", "a", "b"],
        "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-03"],
        "smart_5_raw": [0., np.expm1(1.), np.expm1(3.), 1000.]})
    index = pd.DataFrame({"serial_number": ["a", "b"], "model": ["ST", "ST"],
                          "cutoff_date": ["2024-01-03", "2024-01-03"]})
    base, seq = c.features(history, index, ["smart_5_raw"])
    c.CONFIG["window_contrasts"] = True
    enhanced, new_seq = c.features(history, index, ["smart_5_raw"])
    np.testing.assert_array_equal(seq, new_seq)
    np.testing.assert_allclose(enhanced[:, :6], base[:, :6])
    np.testing.assert_allclose(enhanced[:, 6:8], [[3., 5./3.], [0., 0.]], rtol=1e-6)
    np.testing.assert_array_equal(enhanced[:, 8:], base[:, 6:])


def test_threshold_ties_are_realizable():
    pytest.importorskip("torch")
    import numpy as np
    candidate = module("hdd_dl_threshold", "experiments/hdd_dl/candidate.py")
    y = np.array([1, 0, 1, 0])
    p = np.array([0.9, 0.9, 0.4, 0.1])
    w = np.array([1, 10, 1, 10])
    cut = candidate.threshold(y, p, w)
    assert cut == pytest.approx(0.4)


@pytest.mark.parametrize("family", ["mlp", "tcn", "gru", "dual"])
@pytest.mark.parametrize("normalization,folds", [("standard", 1), ("quantile", 3)])
@pytest.mark.parametrize("max_pool", [False, True])
@pytest.mark.parametrize("ema_decay", [0.0, 0.99])
def test_real_gpu_training_outputs_finite_predictions(family, normalization, folds, max_pool, ema_decay):
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA device required")
    import numpy as np
    candidate = module("hdd_dl_gpu", "experiments/hdd_dl/candidate.py")
    rng = np.random.default_rng(7)
    tab = rng.normal(size=(80, 8)).astype("float32")
    seq = rng.normal(size=(80, 4, 14)).astype("float32")
    y = np.tile([0, 1], 40).astype("float32")
    cfg = {**controller.DEFAULT, "family": family, "epochs": 2, "width": 16, "depth": 1,
           "temporal_max_pool": max_pool,
           "ema_decay": ema_decay,
           "normalization": normalization, "folds": folds, "focal_gamma": 2.0, "ranking_weight": 0.1,
           "epoch_objective": "operational_proxy" if folds == 3 else "auprc",
           "tree_blend": 0.25 if family == "mlp" else 0.0}
    scores, alarms = candidate.fit_predict(tab, seq, y, np.ones(80, dtype="float32"),
                                          tab[:7], seq[:7], cfg)
    assert scores.shape == (7,)
    assert np.isfinite(scores).all()
    assert ((scores >= 0) & (scores <= 1)).all()
    assert alarms.dtype == bool


def test_full_quantiles_fit_only_inner_training(monkeypatch):
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA device required")
    import numpy as np
    c = module("hdd_full_quantiles", "experiments/hdd_dl/candidate.py")
    original, fitted = c.QuantileTransformer, []
    class Capture(original):
        def fit(self, x, y=None):
            assert self.subsample is None
            fitted.append(x.copy())
            return super().fit(x, y)
    monkeypatch.setattr(c, "QuantileTransformer", Capture)
    tab = np.arange(160, dtype=np.float32).reshape(80, 2)
    seq = np.zeros((80, 2, 14), dtype=np.float32)
    train, valid = np.arange(60), np.arange(60, 80)
    cfg = {**controller.DEFAULT, "family": "mlp", "normalization": "quantile",
           "quantile_subsample": None, "epochs": 1, "width": 16, "tree_blend": 0.0}
    scores, _ = c.fit_one(tab, seq, np.tile([0, 1], 40).astype(np.float32),
                         np.ones(80, dtype=np.float32), tab[:2] + 1000, seq[:2], cfg, train, valid)
    assert len(fitted) == 1 and np.isfinite(scores).all()
    np.testing.assert_array_equal(fitted[0], tab[train])


def test_far_floor_honors_weights_ties_and_no_alarm_case():
    pytest.importorskip("torch")
    import numpy as np
    c = module("hdd_far_floor", "experiments/hdd_dl/candidate.py")
    y = np.array([1., 0., 0., 1.])
    p = np.array([.9, .8, .8, .7])
    w = np.array([1., 1., 9., 1.])
    cut = c.far_threshold_floor(y, p, w, .2)
    assert cut == .9 and np.sum(w * (1-y) * (p >= cut)) == 0
    assert c.far_threshold_floor(y, p, w, 1.) == .7
    tied = np.ones(4)
    assert c.far_threshold_floor(y, tied, w, 0.) > 1.
    with pytest.raises(ValueError):
        c.far_threshold_floor(y, p, w, float("nan"))
    with pytest.raises(ValueError):
        c.far_threshold_floor(np.ones(4), p, w, .2)


def test_threshold_diagnostics_distinguish_active_floor_without_changing_cut(monkeypatch):
    pytest.importorskip("torch")
    import numpy as np
    c = module("hdd_threshold_diagnostics", "experiments/hdd_dl/candidate.py")
    y, p, w = np.array([1., 0., 1., 0.]), np.array([.9, .8, .7, .1]), np.ones(4)
    monkeypatch.setattr(c, "calibration_threshold", lambda *args: .7)
    for scale, active, changes in [(1., True, 2), (1.3, False, 0)]:
        cfg = {"threshold_scale": scale, "alarm_far_budget": 0.0}
        diagnostics = {}
        cut = c.select_alarm_threshold(y, p, w, cfg, diagnostics)
        assert cut == c.select_alarm_threshold(y, p, w, cfg)
        assert diagnostics["floor_active"] is active
        assert diagnostics["changed_oof_alarms"] == changes
        assert diagnostics["final_rates"]["far"] == 0
        assert diagnostics["scope"] == "training_oof_only"


def test_causal_temporal_context_covers_oldest_day_without_future_dependency():
    torch = pytest.importorskip("torch")
    c = module("hdd_causal_context", "experiments/hdd_dl/candidate.py")
    for context in ("local", "causal14"):
        model = c.Network(2, 2, {**controller.DEFAULT, "family": "tcn", "temporal_context": context})
        for layer in model.conv.modules():
            if isinstance(layer, torch.nn.Conv1d):
                torch.nn.init.constant_(layer.weight, .01)
                torch.nn.init.constant_(layer.bias, .1)
        x = torch.ones(1, 2, 14, requires_grad=True)
        z = model.conv(x)
        assert z.shape == (1, 32, 14)
        z[:, :, -1].sum().backward()
        if context == "causal14":
            assert (x.grad[:, :, 0] > 0).all()
            changed = x.detach().clone()
            changed[:, :, 7:] = 100
            assert torch.allclose(model.conv(changed)[:, :, :7], z[:, :, :7])
        else:
            assert (x.grad[:, :, 0] == 0).all()


def test_weighted_tail_risk_matches_explicit_objective_and_gradients():
    torch = pytest.importorskip("torch")
    c = module("hdd_tail_risk_math", "experiments/hdd_dl/candidate.py")
    loss = c.WeightedTailRisk(4, beta=.5).double()
    loss.thresholds.fill_(.2)
    z = torch.tensor([.3, -.2, .9, -1.], dtype=torch.float64, requires_grad=True)
    y = torch.tensor([1., 1., 0., 0.], dtype=torch.float64)
    w = torch.tensor([1., 3., 2., 6.], dtype=torch.float64)
    ids = torch.arange(4)
    actual = loss(z, y, w, ids, update=False)
    pairs = torch.nn.functional.softplus(z[2:][None, :] - z[:2, None])
    expected = ((.2 + ((pairs - .2).clamp_min(0) * torch.tensor([.25, .75])).sum(1) / .5)
                * torch.tensor([.25, .75])).sum()
    assert torch.allclose(actual, expected)
    assert torch.autograd.gradcheck(lambda value: loss(value, y, w, ids, update=False), (z,))
    assert torch.allclose(actual, loss(z, y, w * 10, ids, update=False))


def test_tail_state_is_positive_indexed_persistent_and_isolated():
    torch = pytest.importorskip("torch")
    c = module("hdd_tail_risk_state", "experiments/hdd_dl/candidate.py")
    loss, other = c.WeightedTailRisk(6, beta=.5), c.WeightedTailRisk(6, beta=.5)
    initial = loss.thresholds.clone()
    z = torch.tensor([0., 2.], requires_grad=True)
    y, w, ids = torch.tensor([1., 0.]), torch.ones(2), torch.tensor([4, 1])
    value = loss(z, y, w, ids)
    value.backward()
    assert z.grad[0] < 0 and z.grad[1] > 0
    assert loss.thresholds[4] > initial[4]
    assert torch.equal(loss.thresholds[:4], initial[:4])
    assert torch.equal(other.thresholds, initial)
    saved = loss.thresholds.clone()
    loss(z, y, w, ids, update=False)
    assert torch.equal(loss.thresholds, saved)
    loss(z, y, w, ids)
    assert loss.thresholds[4] > saved[4]
    for labels, weights in ((torch.ones(2), w), (y, torch.zeros(2))):
        before = loss.thresholds.clone()
        assert loss(z, labels, weights, ids).item() == 0
        assert torch.equal(loss.thresholds, before)
    with pytest.raises(ValueError):
        loss(z, y, w, torch.tensor([1, 1]))
    with pytest.raises(ValueError):
        loss(z, y, w, torch.tensor([1, 6]))


@pytest.mark.parametrize("beta", [0., -.1, 1.1, float("nan")])
def test_tail_risk_rejects_invalid_region(beta):
    pytest.importorskip("torch")
    c = module("hdd_tail_risk_invalid", "experiments/hdd_dl/candidate.py")
    with pytest.raises(ValueError):
        c.WeightedTailRisk(4, beta=beta)


@pytest.mark.parametrize("refresh", [False, True])
def test_tail_training_warmup_and_local_state_exclude_validation(monkeypatch, refresh):
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA device required")
    import numpy as np
    c = module("hdd_tail_integration", "experiments/hdd_dl/candidate.py")
    states, calls, refreshes = [], [], []
    original = c.WeightedTailRisk
    class Capture(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            states.append(self)
        def refresh(self, logits, labels, weights):
            assert len(logits) == 60
            refreshes.append(self)
            return super().refresh(logits, labels, weights)
        def forward(self, logits, labels, weights, indices, update=True):
            assert update and len(indices) == 60
            assert set(indices.cpu().tolist()) == set(range(60))
            calls.append(self)
            return super().forward(logits, labels, weights, indices, update)
    monkeypatch.setattr(c, "WeightedTailRisk", Capture)
    rng = np.random.default_rng(3)
    tab = rng.normal(size=(80, 3)).astype(np.float32)
    seq = np.zeros((80, 2, 14), dtype=np.float32)
    cfg = {**controller.DEFAULT, "family": "mlp", "epochs": 2, "width": 16,
           "tree_blend": 0., "tail_risk_weight": .01, "tail_warmup_epochs": 1,
           "tail_refresh": refresh}
    for _ in range(2):
        diagnostics = {}
        p, _ = c.fit_one(tab, seq, np.tile([0, 1], 40).astype(np.float32),
            np.ones(80, dtype=np.float32), tab[:2], seq[:2], cfg, np.arange(20, 80), np.arange(20),
            diagnostics=diagnostics)
        assert np.isfinite(p).all()
        assert diagnostics["epochs_completed"] == 2 and diagnostics["tail_batches"] == 1
        assert diagnostics["selected_tail_stage"] == (diagnostics["best_epoch"] >= 1)
        assert np.isfinite(diagnostics["mean_tail_loss"])
        assert diagnostics["positive_thresholds"]["min"] >= 0
    assert len(states) == len(calls) == 2 and states[0] is not states[1]
    assert len(refreshes) == (2 if refresh else 0)
    assert states[0].thresholds.data_ptr() != states[1].thresholds.data_ptr()


def test_tail_mass_diagnostics_use_weighted_negatives_without_mutating_state():
    torch = pytest.importorskip("torch")
    c = module("hdd_tail_mass", "experiments/hdd_dl/candidate.py")
    z, y = torch.tensor([0., 2., -2.]), torch.tensor([1., 0., 0.])
    w, state = torch.tensor([5., 1., 3.]), torch.tensor([1., 0., 0.])
    before = state.clone()
    d = c.tail_mass_diagnostics(z, y, w, state, .25)
    assert d["weighted_mean_mass"] == pytest.approx(.25)
    assert d["weighted_absolute_beta_gap"] == 0
    assert d["weighted_stationary_interval_fraction"] == 1
    assert d["negative_effective_sample_count"] == pytest.approx(1.6)
    assert torch.equal(state, before)


def test_tail_refresh_weighted_quantile_and_ties():
    torch = pytest.importorskip("torch")
    c = module("hdd_tail_refresh", "experiments/hdd_dl/candidate.py")
    z = torch.tensor([0., 1., 3., 2., 2., -1.], dtype=torch.float64)
    y = torch.tensor([1., 1., 0., 0., 0., 0.], dtype=torch.float64)
    w = torch.tensor([1., 2., 1., 2., 3., 4.], dtype=torch.float64)
    risk = c.WeightedTailRisk(6, beta=.2).double()
    before = risk.thresholds.clone()
    risk.refresh(z, y, w)
    assert torch.allclose(risk.thresholds[:2], torch.nn.functional.softplus(2 - z[:2]))
    assert torch.equal(risk.thresholds[2:], before[2:])
    pairs = torch.nn.functional.softplus(z[2:][None, :] - z[:2, None])
    strict = ((pairs > risk.thresholds[:2, None]) * (w[2:] / w[2:].sum())).sum(1)
    inclusive = ((pairs >= risk.thresholds[:2, None]) * (w[2:] / w[2:].sum())).sum(1)
    assert (strict <= .2).all() and (inclusive >= .2).all()
    saved = risk.thresholds.clone()
    risk.refresh(z, y, w * 10)
    assert torch.equal(saved, risk.thresholds)
    with pytest.raises(ValueError):
        risk.refresh(z[:2], y[:2], w[:2])


def test_balanced_selection_prefers_closing_worst_metric_gap():
    baseline = result()
    balanced, high_ros = result(0.6), result(0.8)
    for key in controller.LOWER:
        balanced["metric"][key] = 0.4
        high_ros["metric"][key] = 0.2
    balanced["combined_score"], high_ros["combined_score"] = 35, 50
    high_ros["metric"]["recall"] = 0.1
    rows = []
    for i, value in enumerate([balanced, high_ros]):
        rows.append({"trial": i, "config": dict(controller.DEFAULT), "result": value,
                     "comparisons": [controller.comparison(value, baseline)]})
    assert controller.weakest_margin(rows[0]) > controller.weakest_margin(rows[1])
    _, parent, _ = controller.propose(10, rows)
    assert parent == 0


def test_resource_selection_exposes_runtime_gap_without_changing_gates():
    baseline = result()
    rows = []
    for i, runtime in enumerate([5.0, 0.6]):
        value = result(0.6)
        value["metric"]["run_time_s"] = runtime
        value["combined_score"] = 50 - i
        rows.append({"trial": i, "config": dict(controller.DEFAULT), "result": value,
                     "comparisons": [controller.comparison(value, baseline)]})
    assert controller.resource_margin(rows[1]) > controller.resource_margin(rows[0])
    assert controller.propose(9, rows)[1] == 0
    assert controller.propose(9, rows, resource_selection=True)[1] == 1
    assert not rows[1]["comparisons"][0]["all_including_resources_strictly_better"]
    del rows[1]["comparisons"][0]["metrics"]["run_time_s"]
    assert controller.resource_margin(rows[1]) == -float("inf")


def test_predictive_resource_rank_rejects_fast_but_weak_tradeoff():
    baseline = result()
    rows = []
    for quality, seconds in [(0.6, 20.0), (0.4, 0.01), (0.7, 10.0)]:
        value = result(quality)
        value["combined_score"] = 40
        for key in controller.LOWER:
            value["metric"][key] = 0.4
        value["metric"]["run_time_s"] = seconds
        rows.append({"result": value, "comparisons": [controller.comparison(value, baseline)]})
    assert controller.resource_margin(rows[1]) > controller.resource_margin(rows[0])
    assert controller.predictive_resource_rank(rows[0]) > controller.predictive_resource_rank(rows[1])
    assert controller.predictive_resource_rank(rows[2]) > controller.predictive_resource_rank(rows[0])
    rows[0]["comparisons"][0]["metrics"]["recall"]["candidate"] = 0.5
    assert controller.predictive_resource_rank(rows[0])[0] == 0
    rows[2]["result"]["validity"] = 0
    assert controller.predictive_resource_rank(rows[2])[0] == -1


def test_predictive_resource_rank_closes_prediction_gap_before_speed():
    rows = []
    for quality, seconds in [(0.49, 20.0), (0.3, 0.01)]:
        value = result(quality)
        value["metric"]["run_time_s"] = seconds
        rows.append({"result": value, "comparisons": [controller.comparison(value, result())]})
    assert controller.predictive_resource_rank(rows[0]) > controller.predictive_resource_rank(rows[1])
    del rows[0]["comparisons"][0]["metrics"]["run_time_s"]
    assert controller.predictive_resource_rank(rows[0])[0] == -1


def test_seed_reuses_configs_without_importing_scores():
    record = {"config": dict(controller.DEFAULT), "result": result(), "trial": 99}
    seeds = controller.seed_configs([record])
    config, parent, _ = controller.propose(0, [], initial_configs=seeds)
    assert config == controller.DEFAULT
    assert parent is None
    assert "result" not in config
    record["config"]["seed"] = 42
    with pytest.raises(ValueError, match="random seed"):
        controller.seed_configs([record])


def test_profile_counts_independent_entities_not_rows(tmp_path):
    import pandas as pd
    context = module("hdd_context", "experiments/hdd_dl/research_context.py")
    labels = tmp_path / "train_labels.csv"
    history = tmp_path / "train_history.csv.gz"
    pd.DataFrame({"serial_number": ["a", "b"], "label": [0, 1],
                  "model": ["ST", "ST"], "cutoff_date": ["2024-01-01"] * 2}).to_csv(labels, index=False)
    pd.DataFrame({"serial_number": ["a"] * 100 + ["b"] * 100}).to_csv(history, index=False)
    profile = context.profile_training({"train_labels.csv": labels, "train_history.csv.gz": history}, True)
    assert profile["training_entities"] == 2
    assert profile["training_history_rows"] == 200
    assert profile["route"] == "ml_only"
    assert "serial_number" not in profile


def test_retrieval_deduplicates_and_marks_metadata_only():
    import httpx
    context = module("hdd_retrieval", "experiments/hdd_dl/research_context.py")
    seen = []
    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"message": {"items": [
            {"DOI": "10.1234/example", "title": ["Hard disk failure prediction with recurrent networks"]},
            {"DOI": "10.1234/noise", "title": ["Unrelated material"]}]}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = context.retrieve({"median_observations_per_entity": 14}, client)
    assert len(seen) == 2
    assert len(result["cards"]) == 1
    assert result["cards"][0]["action"] == {"family": "gru"}
    assert result["cards"][0]["verification"] == "bibliographic_metadata_only"
    assert not result["raw_data_uploaded"]


def test_retrieval_failure_does_not_invent_evidence():
    import httpx
    context = module("hdd_retrieval_failure", "experiments/hdd_dl/research_context.py")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        result = context.retrieve({"median_observations_per_entity": 14}, client)
    assert result["cards"] == []
    assert all(event["status"] == "unavailable" for event in result["events"])


def test_seed_verification_cannot_pass_partial_or_duplicate_seeds():
    verification = module("hdd_verification", "experiments/hdd_dl/verify.py")
    comparison = {"all_predictive_strictly_better": True,
                  "all_including_resources_strictly_better": True}
    row = {"candidate": "frozen.py", "seed": 1, "result": result(), "comparisons": [comparison]}
    assert not verification.aggregate([row], 3)["frozen.py"]["all_seeds_all_metrics_better"]
    assert not verification.aggregate([row, row, row], 3)["frozen.py"]["all_seeds_all_metrics_better"]
    rows = [{**row, "seed": seed} for seed in [1, 2, 3]]
    assert verification.aggregate(rows, 3)["frozen.py"]["all_seeds_all_metrics_better"]
    rows[1]["comparisons"] = []
    assert not verification.aggregate(rows, 3)["frozen.py"]["all_seeds_all_metrics_better"]


def test_verification_changes_only_seed_in_literal_config():
    verification = module("hdd_verification_config", "experiments/hdd_dl/verify.py")
    source = controller.render((ROOT / "experiments/hdd_dl/candidate.py").read_text(encoding="utf-8"), controller.DEFAULT)
    config = verification.config_from_source(source)
    config["seed"] = 123
    rewritten = controller.render(source, config)
    recovered = verification.config_from_source(rewritten)
    assert recovered.pop("seed") == 123
    assert recovered == {k: v for k, v in controller.DEFAULT.items() if k != "seed"}


def test_operational_proxy_handles_score_ties_without_fake_recall():
    pytest.importorskip("torch")
    import numpy as np
    candidate = module("hdd_proxy", "experiments/hdd_dl/candidate.py")
    assert candidate.operational_proxy(np.array([1, 0]), np.array([0.9, 0.1]), np.ones(2), 1) == 1
    tied = candidate.operational_proxy(np.array([1, 0]), np.array([0.5, 0.5]), np.ones(2), 0.5)
    assert tied == pytest.approx(0.5 * (2 / 3) + 0.3 * 0.5)


def test_planner_budget_and_resume_do_not_repeat_paid_calls(tmp_path, monkeypatch):
    import httpx
    import json
    planner = module("hdd_planner_test", "experiments/hdd_dl/planner.py")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-secret-not-real")
    calls = []
    proposal = {"changes": {"dropout": 0.25}, "hypothesis": "测试正则化。",
                "knowledge_ids": ["known"], "evidence_trials": [0]}
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(proposal)}}],
                                        "usage": {"total_tokens": 20}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        arguments = dict(parent=controller.DEFAULT,
                         records=[{"trial": 0, "config": controller.DEFAULT, "result": result()}],
                         knowledge=[{"id": "known"}], space=controller.SPACE,
                         ledger_path=tmp_path / "ledger.json", write_json=controller.write_json,
                         max_calls=1, client=client)
        assert planner.propose(trial=7, **arguments) == proposal
        assert planner.propose(trial=7, **arguments) == proposal
        assert planner.propose(trial=15, **arguments) is None
    assert len(calls) == 1
    assert "test-secret-not-real" not in (tmp_path / "ledger.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("changes", [{"seed": 1}, {"family": "shell command"}, {"model_identity": 1}])
def test_planner_rejects_unapproved_changes(changes):
    planner = module("hdd_planner_validation", "experiments/hdd_dl/planner.py")
    with pytest.raises(ValueError):
        planner.validate({"changes": changes, "hypothesis": "hypothesis",
                          "knowledge_ids": [], "evidence_trials": []}, controller.SPACE, set(), set())


def test_duplicate_search_proposals_are_replaced_deterministically_without_score_reuse():
    records = [{"config": controller.DEFAULT, "result": result()}]
    candidate, replaced = controller.unseen_config(controller.DEFAULT, records, 10, ["tcn", "mlp"])
    assert replaced
    assert candidate != controller.DEFAULT
    assert candidate["seed"] == controller.DEFAULT["seed"]
    assert candidate["train_seconds"] == controller.DEFAULT["train_seconds"]
    assert (candidate, replaced) == controller.unseen_config(controller.DEFAULT, records, 10, ["tcn", "mlp"])
    assert controller.unseen_config(candidate, records, 11, ["tcn", "mlp"]) == (candidate, False)
    assert records == [{"config": controller.DEFAULT, "result": result()}]


def test_planner_feedback_includes_recent_failed_and_low_scoring_trials():
    planner = module("hdd_feedback", "experiments/hdd_dl/planner.py")
    records = [{"trial": i, "config": controller.DEFAULT,
                "result": {**result(), "combined_score": 100-i}} for i in range(12)]
    records[-1]["result"] = {"validity": 0, "error": "not sent externally"}
    feedback = planner.summarize(records)
    assert {0, 1, 2, 3, 4, 6, 7, 8, 9, 10, 11} == {r["trial"] for r in feedback}
    assert feedback[-1]["validity"] == 0
    assert "error" not in feedback[-1]


@pytest.mark.parametrize("families", [None, ["tcn", "gru", "mlp"]])
@pytest.mark.parametrize("replicas", [3, 9])
def test_replica_ensemble_calibrates_averaged_unseen_predictions_and_shares_budget(monkeypatch, families, replicas):
    pytest.importorskip("torch")
    import numpy as np
    candidate = module("hdd_replicas", "experiments/hdd_dl/candidate.py")
    calls, calibration = [], []
    families = families * (replicas // 3) if families is not None else None
    def fit(tab, seq, y, w, qt, qs, cfg, train, valid):
        assert not set(train) & set(valid)
        calls.append((cfg, tuple(valid)))
        probability = [0.2, 0.5, 0.8][(len(calls)-1) % 3]
        return np.full(len(qt), probability), np.full(len(valid), probability)
    def threshold(y, p, w):
        calibration.append(p)
        return 0.4
    monkeypatch.setattr(candidate, "fit_one", fit)
    monkeypatch.setattr(candidate, "threshold", threshold)
    tab, seq = np.zeros((30, 2)), np.zeros((30, 2, 14))
    scores, alarms = candidate.fit_predict(
        tab, seq, np.tile([0, 1], 15), np.ones(30), tab[:2], seq[:2],
        {**controller.DEFAULT, "replicas": replicas, "folds": 3,
         **({"replica_families": families} if families is not None else {})})
    assert len(calls) == 3 * replicas
    expected = families or [controller.DEFAULT["family"]] * replicas
    assert [cfg["family"] for cfg, _ in calls] == expected * 3
    assert len({cfg["seed"] for cfg, _ in calls}) == 3 * replicas
    assert sum(cfg["train_seconds"] for cfg, _ in calls) == pytest.approx(240)
    for start in range(0, 3 * replicas, replicas):
        assert len({valid for _, valid in calls[start:start + replicas]}) == 1
    assert len(calibration[0]) == 30
    assert np.allclose(calibration[0], 0.5)
    assert np.allclose(scores, 0.5) and alarms.all()


@pytest.mark.parametrize("partition", ["oof", "shared_calibration"])
def test_calibration_partition_exposes_fold_averaging_difference(monkeypatch, partition):
    pytest.importorskip("torch")
    import numpy as np
    c = module("hdd_partition", "experiments/hdd_dl/candidate.py")
    calls, held, calibrated = [], [], []
    def fit(tab, seq, y, w, qt, qs, cfg, train, valid):
        assert not set(train) & set(valid)
        value = [.2, .5, .8][len(calls) // 3]
        calls.append(cfg)
        held.append(tuple(valid))
        return np.full(len(qt), value), np.full(len(valid), value)
    def select(y, p, w, cfg, diagnostics):
        calibrated.append(p)
        return .4
    monkeypatch.setattr(c, "fit_one", fit)
    monkeypatch.setattr(c, "select_alarm_threshold", select)
    tab, seq = np.zeros((120, 2)), np.zeros((120, 2, 14))
    scores, _ = c.fit_predict(tab, seq, np.tile([0, 1], 60), np.ones(120), tab[:2], seq[:2],
        {**controller.DEFAULT, "folds": 3, "replicas": 3, "calibration_partition": partition})
    assert len(calls) == 9 and sum(x["train_seconds"] for x in calls) == pytest.approx(240)
    assert np.allclose(scores, .5)
    if partition == "shared_calibration":
        assert len(set(held)) == 1 and len(calibrated[0]) == 12
        assert np.allclose(calibrated[0], scores[0])
    else:
        assert len(set(held)) == 3 and len(calibrated[0]) == 120
        assert np.std(calibrated[0]) > .2


def test_paired_report_requires_all_metrics_and_matched_valid_seeds():
    paired = module("hdd_paired", "experiments/hdd_dl/paired_report.py")
    records = []
    for seed in [1, 2, 3]:
        for name, score in [("control", 40), ("treatment", 42)]:
            records.append({"candidate": name, "seed": seed,
                            "result": {**result(), "combined_score": score}})
    report = paired.compare(records, "control", "treatment", [1, 2, 3])
    assert report["metrics"]["combined_score"]["mean_delta"] == 2
    assert report["metrics"]["combined_score"]["strict_wins"] == 3
    records[-1]["result"]["validity"] = 0
    assert not paired.compare(records, "control", "treatment", [1, 2, 3])["complete"]
    with pytest.raises(ValueError, match="Duplicate"):
        paired.compare(records + [records[0]], "control", "treatment", [1, 2, 3])


def test_hard_negative_ranking_has_correct_gradients_and_handles_single_class():
    torch = pytest.importorskip("torch")
    candidate = module("hdd_ranking", "experiments/hdd_dl/candidate.py")
    logits = torch.tensor([0.0, 1.0, -1.0], requires_grad=True)
    loss = candidate.hard_negative_ranking(logits, torch.tensor([1, 0, 0]), torch.ones(3))
    loss.backward()
    assert logits.grad[0] < 0
    assert (logits.grad[1:] > 0).all()
    for label in [0, 1]:
        single = torch.ones(3, requires_grad=True)
        zero = candidate.hard_negative_ranking(single, torch.full((3,), label), torch.ones(3))
        zero.backward()
        assert zero.item() == 0 and (single.grad == 0).all()


def test_ranking_tail_count_restricts_gradients_and_reaches_member_loss():
    torch = pytest.importorskip("torch")
    c = module("hdd_tail_ranking", "experiments/hdd_dl/candidate.py")
    z = torch.tensor([0.0, 2.0, -1.0], requires_grad=True)
    y, w = torch.tensor([1.0, 0.0, 0.0]), torch.ones(3)
    c.hard_negative_ranking(z, y, w, 1).backward()
    assert z.grad[0] < 0 and z.grad[1] > 0 and z.grad[2] == 0
    members = torch.stack([z.detach(), z.detach() + 0.5], dim=1)
    base = c.training_loss(members, y, w, torch.tensor(1.0))
    actual = c.training_loss(members, y, w, torch.tensor(1.0), ranking_weight=0.01,
                             ranking_negatives=1)
    assert torch.allclose(actual - base, 0.01 * torch.nn.functional.softplus(torch.tensor(2.0)))
    for invalid in (0, -1, 1.5, True):
        with pytest.raises(ValueError, match="positive integer"):
            c.hard_negative_ranking(z, y, w, invalid)


def test_device_context_tracks_calendar_gaps_resets_and_index_order():
    pytest.importorskip("torch")
    import numpy as np
    import pandas as pd
    candidate = module("hdd_device_context", "experiments/hdd_dl/candidate.py")
    history = pd.DataFrame({"serial_number": ["a", "a", "b", "b"],
                            "date": ["2026-01-01", "2026-01-04", "2026-01-02", "2026-01-04"],
                            "capacity_bytes": [100, 100, 200, 200]})
    frame = pd.DataFrame({"serial_number": history.serial_number,
                          "smart_5_raw": [5., 2., 1., 7.]})
    index = pd.DataFrame({"serial_number": ["b", "missing", "a"],
                          "cutoff_date": ["2026-01-05"] * 3})
    actual = candidate.device_context(history, index, frame, ["smart_5_raw"])
    assert actual.shape == (3, 7) and np.isfinite(actual).all()
    assert actual[0, 3] == 2
    assert actual[0, 4] == pytest.approx(np.log1p(200))
    assert actual[0, 5] == 3 and actual[0, 6] == 0
    assert actual[2, 5] == 0 and actual[2, 6] == 1
    assert (actual[1] == 0).all()


@pytest.mark.parametrize("tree_boost", [None, 1.0, 5.0])
@pytest.mark.parametrize("tree_rounds", [150, 300])
@pytest.mark.parametrize("tree_leaves", [15, 31])
@pytest.mark.parametrize("fusion_mode", ["probability", "logit"])
@pytest.mark.parametrize("tree_input", ["normalized", "original"])
@pytest.mark.parametrize("hybrid_selection", [False, True])
def test_hybrid_tree_uses_only_inner_training_and_blends_calibration_equally(monkeypatch, tree_boost, tree_rounds, tree_leaves, fusion_mode, tree_input, hybrid_selection):
    torch = pytest.importorskip("torch")
    lgb = pytest.importorskip("lightgbm")
    if not torch.cuda.is_available():
        pytest.skip("GPU candidate")
    import numpy as np
    candidate = module("hdd_hybrid", "experiments/hdd_dl/candidate.py")
    rng = np.random.default_rng(9)
    tab = rng.normal(size=(80, 4)).astype("float32")
    seq = rng.normal(size=(80, 2, 14)).astype("float32")
    y, w = np.tile([0, 1], 40).astype("float32"), np.ones(80)
    train, valid = np.arange(60), np.arange(60, 80)
    cfg = {**controller.DEFAULT, "epochs": 2, "width": 16, "depth": 1, "tree_blend": 0.0}
    cfg["tree_rounds"] = tree_rounds
    cfg["tree_leaves"] = tree_leaves
    cfg["fusion_mode"] = fusion_mode
    cfg["tree_input"] = tree_input
    cfg["hybrid_selection"] = hybrid_selection
    ap_inputs = []
    real_ap = candidate.average_precision_score
    def capture_ap(labels, predictions, sample_weight):
        np.testing.assert_array_equal(labels, y[valid])
        ap_inputs.append(predictions.copy())
        return real_ap(labels, predictions, sample_weight=sample_weight)
    monkeypatch.setattr(candidate, "average_precision_score", capture_ap)
    if tree_boost is not None:
        cfg["tree_positive_boost"] = tree_boost
    base_q, base_v = candidate.fit_one(tab, seq, y, w, tab[:7], seq[:7], cfg, train, valid)
    calls = []
    class Tree:
        def __init__(self, **kwargs):
            assert kwargs["n_jobs"] == 4 and kwargs["n_estimators"] == tree_rounds
            assert kwargs["num_leaves"] == tree_leaves
        def fit(self, x, labels, sample_weight):
            assert len(x) == 60
            if tree_input == "original":
                np.testing.assert_array_equal(x, tab[train])
            else:
                assert not np.array_equal(x, tab[train])
            np.testing.assert_array_equal(labels, y[train])
            np.testing.assert_allclose(sample_weight, np.where(
                y[train] > 0, cfg.get("tree_positive_boost", cfg["positive_boost"]), 1))
            calls.append("fit")
        def predict_proba(self, x):
            if tree_input == "original":
                np.testing.assert_array_equal(x, tab[:7] if len(x) == 7 else tab[valid])
            calls.append(len(x))
            return np.tile([0.2, 0.8], (len(x), 1))
    monkeypatch.setattr(lgb, "LGBMClassifier", Tree)
    q, v = candidate.fit_one(tab, seq, y, w, tab[:7], seq[:7],
                             {**cfg, "tree_blend": 0.5}, train, valid)
    def expected(p):
        if fusion_mode == "probability":
            return 0.5 * p + 0.4
        odds = np.sqrt((p / (1 - p)) * 4)
        return odds / (1 + odds)
    np.testing.assert_allclose(q, expected(base_q), rtol=1e-6)
    np.testing.assert_allclose(v, expected(base_v), rtol=1e-6)
    assert calls == (["fit", 20, 7, 20] if hybrid_selection else ["fit", 7, 20])
    assert len(ap_inputs) == 4
    for before, after in zip(ap_inputs[:2], ap_inputs[2:]):
        np.testing.assert_allclose(after, expected(before) if hybrid_selection else before, rtol=1e-6)


@pytest.mark.parametrize("family", ["mlp", "tcn", "gru", "dual"])
@pytest.mark.parametrize("crossfit", [False, True])
def test_tree_residual_starts_at_prior_and_uses_it_in_loss_and_predictions(monkeypatch, family, crossfit):
    torch = pytest.importorskip("torch")
    lgb = pytest.importorskip("lightgbm")
    if not torch.cuda.is_available():
        pytest.skip("GPU candidate")
    import numpy as np
    c = module("hdd_residual", "experiments/hdd_dl/candidate.py")
    rng = np.random.default_rng(10)
    tab = rng.normal(size=(80, 4)).astype("float32")
    seq = rng.normal(size=(80, 2, 14)).astype("float32")
    y, w = np.tile([0, 1], 40).astype("float32"), np.ones(80)
    train, valid = np.arange(60), np.arange(60, 80)
    calls, losses = [], []
    class Tree:
        def __init__(self, **kwargs):
            pass
        def fit(self, x, labels, sample_weight):
            if not crossfit:
                np.testing.assert_array_equal(x, tab[train])
                np.testing.assert_array_equal(labels, y[train])
            else:
                assert len(x) == 40
            calls.append("fit")
        def predict_proba(self, x):
            calls.append(len(x))
            return np.tile([0.2, 0.8], (len(x), 1))
    monkeypatch.setattr(lgb, "LGBMClassifier", Tree)
    real_loss = c.nn.functional.binary_cross_entropy_with_logits
    def capture_loss(logits, labels, **kwargs):
        np.testing.assert_allclose(logits.detach().cpu().numpy(), np.log(4), rtol=1e-6)
        losses.append(len(logits))
        return real_loss(logits, labels, **kwargs)
    monkeypatch.setattr(c.nn.functional, "binary_cross_entropy_with_logits", capture_loss)
    cfg = {**controller.DEFAULT, "family": family, "epochs": 2, "width": 16,
           "depth": 1, "lr": 0.0, "tree_blend": 0.5, "tree_residual": True,
           "tree_input": "original", "residual_crossfit": crossfit}
    q, v = c.fit_one(tab, seq, y, w, tab[:7], seq[:7], cfg, train, valid)
    np.testing.assert_allclose(q, 0.8, rtol=1e-6)
    np.testing.assert_allclose(v, 0.8, rtol=1e-6)
    assert calls == (["fit", 20, 20, 7] * 3 if crossfit else ["fit", 80, 7])
    assert sum(losses) == 120
    with pytest.raises(ValueError, match="tree_residual"):
        c.fit_one(tab, seq, y, w, tab[:7], seq[:7], {**cfg, "tree_blend": 0}, train, valid)


def test_crossfit_tree_prior_never_predicts_training_entities_with_their_own_labels(monkeypatch):
    pytest.importorskip("torch")
    import numpy as np
    c = module("hdd_crossfit_prior", "experiments/hdd_dl/candidate.py")
    tab = np.arange(90, dtype=np.float32)[:, None]
    query = np.array([[100], [101]], dtype=np.float32)
    y, w = np.tile([0, 1], 45), np.ones(90)
    train = np.arange(0, 90, 3)
    fitted = []
    def fit(t, labels, weights, cfg, ids):
        assert set(ids).issubset(set(train))
        fitted.append(set(ids))
        class Memorizer:
            def predict_proba(self, x):
                p = np.array([0.99 if int(a[0]) in set(ids) else 0.2 for a in x])
                return np.column_stack([1 - p, p])
        return Memorizer()
    monkeypatch.setattr(c, "fit_tree_branch", fit)
    p, q = c.crossfit_tree_prior(tab, query, y, w, {"seed": 17}, train)
    np.testing.assert_allclose(p, 0.2)
    np.testing.assert_allclose(q, 0.2)
    assert len(fitted) == 3 and all(len(ids) == 20 for ids in fitted)
    assert all(sum(i in ids for ids in fitted) == 2 for i in train)


def test_fold_alignment_uses_inner_validation_scale_for_query_and_oof(monkeypatch):
    pytest.importorskip("torch")
    import numpy as np
    candidate = module("hdd_fold_alignment", "experiments/hdd_dl/candidate.py")
    fits, cuts = [], []
    def fit(tab, seq, y, w, qt, qs, cfg, train, valid):
        value = [0.2, 0.4, 0.8][len(fits)]
        fits.append(tuple(valid))
        return np.full(len(qt), value / 2), np.full(len(valid), value)
    def threshold(y, p, w):
        cuts.append(p.copy())
        return float(p[0])
    monkeypatch.setattr(candidate, "fit_one", fit)
    monkeypatch.setattr(candidate, "threshold", threshold)
    tab, seq = np.zeros((30, 2)), np.zeros((30, 2, 14))
    p, alarms = candidate.fit_predict(tab, seq, np.tile([0, 1], 15), np.ones(30),
        tab[:2], seq[:2], {**controller.DEFAULT, "folds": 3, "replicas": 1,
                          "fold_calibration": "threshold_ratio", "threshold_scale": 1})
    assert len(cuts) == 4 and len(cuts[-1]) == 30
    assert np.allclose(cuts[-1], 0.5)
    assert np.allclose(p, 1/3) and not alarms.any()


def test_planner_reserves_failed_request_and_cannot_invent_evidence(tmp_path, monkeypatch):
    import httpx
    import json
    planner = module("hdd_planner_failure", "experiments/hdd_dl/planner.py")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-secret")
    response = {"changes": {"lr": 0.001}, "hypothesis": "test",
                "knowledge_ids": ["invented"], "evidence_trials": []}
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(response)}}]}))) as client:
        actual = planner.propose(trial=7, parent=controller.DEFAULT, records=[], knowledge=[],
                                 space=controller.SPACE, ledger_path=tmp_path / "ledger.json",
                                 write_json=controller.write_json, max_calls=1, client=client)
    assert actual is None
    ledger = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))
    assert len(ledger) == 1
    assert ledger[0]["status"] == "failed"


def test_shared_preprocessing_is_fold_local_and_preserves_replica_seeds(monkeypatch):
    pytest.importorskip('torch')
    import numpy as np
    c = module('hdd_shared_preprocessing', 'experiments/hdd_dl/candidate.py')
    prepared_calls, fit_calls = [], []
    def prepare(tab, seq, qt, qs, cfg, train):
        result = (tab.copy(), seq.copy(), qt.copy(), qs.copy())
        prepared_calls.append((train.copy(), cfg['seed'], result))
        return result
    def fit(tab, seq, y, w, qt, qs, cfg, train, valid, prepared=None):
        assert not set(train) & set(valid)
        expected = prepared_calls[-1]
        assert np.array_equal(train, expected[0])
        assert prepared is expected[2]
        fit_calls.append((cfg['seed'], prepared))
        return np.full(len(qt), .4), np.full(len(valid), .4)
    monkeypatch.setattr(c, 'prepare_fold_inputs', prepare)
    monkeypatch.setattr(c, 'fit_one', fit)
    tab, seq = np.zeros((60, 3)), np.zeros((60, 2, 14))
    cfg = {**controller.DEFAULT, 'replicas': 3, 'folds': 3, 'share_fold_preprocessing': True}
    c.fit_predict(tab, seq, np.tile([0, 1], 30), np.ones(60), tab[:2], seq[:2], cfg)
    assert len(prepared_calls) == 3 and len(fit_calls) == 9
    assert len({id(x[2]) for x in prepared_calls}) == 3
    assert len({x[0] for x in fit_calls}) == 9
    assert [x[1] for x in prepared_calls] == [cfg['seed'] + i for i in range(3)]


def test_prepare_fold_inputs_fits_training_only_and_does_not_mutate_inputs():
    pytest.importorskip('torch')
    import numpy as np
    c = module('hdd_prepare_inputs', 'experiments/hdd_dl/candidate.py')
    rng = np.random.default_rng(17)
    tab, seq = rng.normal(size=(80, 3)), rng.normal(size=(80, 2, 14))
    original_tab, original_seq = tab.copy(), seq.copy()
    train = np.arange(60)
    cfg = {**controller.DEFAULT, 'normalization': 'quantile'}
    first = c.prepare_fold_inputs(tab, seq, tab[:2], seq[:2], cfg, train)
    altered_tab, altered_seq = tab.copy(), seq.copy()
    altered_tab[60:] = 1e6
    altered_seq[60:] = 1e6
    second = c.prepare_fold_inputs(altered_tab, altered_seq, tab[:2], seq[:2], cfg, train)
    np.testing.assert_array_equal(tab, original_tab)
    np.testing.assert_array_equal(seq, original_seq)
    for a, b in zip(first, second):
        np.testing.assert_allclose(a[:60], b[:60])


def test_shared_tree_trains_once_per_fold_and_keeps_predictions_local(monkeypatch):
    pytest.importorskip('torch')
    import numpy as np
    c = module('hdd_shared_tree', 'experiments/hdd_dl/candidate.py')
    trees, calls = [], []
    def tree_fit(tab, y, w, cfg, train):
        trees.append((train.copy(), cfg['seed']))
        value = .1 * len(trees)
        class Tree:
            def predict_proba(self, x):
                return np.tile([1-value, value], (len(x), 1))
        return Tree()
    def fit(tab, seq, y, w, qt, qs, cfg, train, valid, prepared=None, shared_tree=None):
        assert not set(train) & set(valid)
        np.testing.assert_array_equal(train, trees[-1][0])
        q, v = shared_tree
        assert len(q) == len(qt) and len(v) == len(valid)
        np.testing.assert_allclose(q, .1 * len(trees))
        np.testing.assert_allclose(v, .1 * len(trees))
        calls.append(shared_tree)
        return q, v
    monkeypatch.setattr(c, 'fit_tree_branch', tree_fit)
    monkeypatch.setattr(c, 'fit_one', fit)
    tab, seq = np.zeros((60, 3)), np.zeros((60, 2, 14))
    cfg = {**controller.DEFAULT, 'replicas': 3, 'folds': 3, 'tree_blend': .5,
           'share_fold_preprocessing': True, 'share_fold_tree': True}
    c.fit_predict(tab, seq, np.tile([0, 1], 30), np.ones(60), tab[:2], seq[:2], cfg)
    assert len(trees) == 3 and len(calls) == 9
    assert calls[0] is calls[1] is calls[2]
    assert calls[0] is not calls[3] and calls[3] is not calls[6]
    for change in ({'share_fold_preprocessing': False}, {'tree_blend': 0}, {'tree_residual': True}, {'hybrid_selection': True}):
        with pytest.raises(ValueError, match='Tree sharing requires'):
            c.fit_predict(tab, seq, np.tile([0, 1], 30), np.ones(60), tab[:2], seq[:2], {**cfg, **change})


def test_shared_tree_predictions_blend_query_and_calibration_without_retraining(monkeypatch):
    torch = pytest.importorskip('torch')
    if not torch.cuda.is_available():
        pytest.skip('GPU candidate')
    import numpy as np
    c = module('hdd_shared_tree_gpu', 'experiments/hdd_dl/candidate.py')
    rng = np.random.default_rng(8)
    tab = rng.normal(size=(80, 4)).astype('float32')
    seq = rng.normal(size=(80, 2, 14)).astype('float32')
    y, w = np.tile([0, 1], 40).astype('float32'), np.ones(80)
    train, valid = np.arange(60), np.arange(60, 80)
    cfg = {**controller.DEFAULT, 'epochs': 2, 'width': 16, 'depth': 1, 'tree_blend': 0}
    prepared = c.prepare_fold_inputs(tab, seq, tab[:7], seq[:7], cfg, train)
    q, v = c.fit_one(tab, seq, y, w, tab[:7], seq[:7], cfg, train, valid, prepared=prepared)
    def forbidden(*args):
        pytest.fail('shared tree must not be retrained')
    monkeypatch.setattr(c, 'fit_tree_branch', forbidden)
    tq, tv = np.full(7, .3), np.full(20, .7)
    actual_q, actual_v = c.fit_one(tab, seq, y, w, tab[:7], seq[:7], {**cfg, 'tree_blend': .5}, train, valid, prepared=prepared, shared_tree=(tq, tv))
    np.testing.assert_allclose(actual_q, .5 * (q + tq), atol=1e-7)
    np.testing.assert_allclose(actual_v, .5 * (v + tv), atol=1e-7)


def test_fused_optimizer_performs_finite_gpu_training(monkeypatch):
    torch = pytest.importorskip('torch')
    if not torch.cuda.is_available():
        pytest.skip('GPU candidate')
    import numpy as np
    c = module('hdd_fused_optimizer', 'experiments/hdd_dl/candidate.py')
    real = c.torch.optim.AdamW
    optimizers = []
    def create(*args, **kwargs):
        assert kwargs['fused'] is True
        optimizer = real(*args, **kwargs)
        optimizers.append(optimizer)
        return optimizer
    monkeypatch.setattr(c.torch.optim, 'AdamW', create)
    rng = np.random.default_rng(12)
    tab = rng.normal(size=(80, 4)).astype('float32')
    seq = rng.normal(size=(80, 2, 14)).astype('float32')
    y, w = np.tile([0, 1], 40).astype('float32'), np.ones(80)
    cfg = {**controller.DEFAULT, 'epochs': 2, 'width': 16, 'depth': 1,
           'fused_optimizer': True, 'tree_blend': 0}
    q, v = c.fit_one(tab, seq, y, w, tab[:7], seq[:7], cfg, np.arange(60), np.arange(60, 80))
    assert q.shape == (7,) and v.shape == (20,)
    assert np.isfinite(q).all() and np.isfinite(v).all()
    assert ((q >= 0) & (q <= 1)).all()
    states = list(optimizers[0].state.values())
    assert states and all(float(state['step']) > 0 for state in states)
    assert all(torch.isfinite(state['exp_avg']).all() for state in states)


def test_temporal_attention_starts_at_mean_and_can_learn_nonuniform_weights():
    torch = pytest.importorskip('torch')
    c = module('hdd_temporal_attention', 'experiments/hdd_dl/candidate.py')
    pool = c.TemporalAttentionPool(2).double()
    z = torch.tensor([[[0., 1., 3.], [2., 0., 1.]]], dtype=torch.float64, requires_grad=True)
    torch.testing.assert_close(pool(z), z.mean(dim=2))
    pool(z).sum().backward()
    assert torch.isfinite(pool.direction.grad).all()
    assert pool.direction.grad.abs().sum() > 0
    with torch.no_grad():
        pool.direction.copy_(torch.tensor([2., -1.]))
    expected_weights = torch.softmax(2*z[:, 0] - z[:, 1], dim=1)
    torch.testing.assert_close(pool(z), (z*expected_weights[:, None]).sum(dim=2))
    assert not torch.allclose(pool(z), z.mean(dim=2))
    assert torch.autograd.gradcheck(pool, (z.detach().requires_grad_(True),))


def test_temporal_attention_keeps_network_input_dimensions_and_initial_outputs():
    torch = pytest.importorskip('torch')
    c = module('hdd_temporal_attention_network', 'experiments/hdd_dl/candidate.py')
    cfg = {**controller.DEFAULT, 'family': 'tcn', 'width': 16, 'depth': 1}
    torch.manual_seed(17)
    base = c.Network(4, 2, cfg).eval()
    torch.manual_seed(17)
    attentive = c.Network(4, 2, {**cfg, 'temporal_attention': True}).eval()
    assert base.input.in_features == attentive.input.in_features
    tab, seq = torch.randn(5, 4), torch.randn(5, 2, 14)
    torch.testing.assert_close(base(tab, seq), attentive(tab, seq), atol=1e-6, rtol=1e-5)
    assert sum(p.numel() for p in attentive.parameters()) - sum(p.numel() for p in base.parameters()) == 32
    with pytest.raises(ValueError, match='temporal convolution'):
        c.Network(4, 2, {**cfg, 'family': 'mlp', 'temporal_attention': True})


@pytest.mark.parametrize('changes', [
    {'share_fold_preprocessing': False}, {'tree_blend': 0},
    {'tree_residual': True}, {'hybrid_selection': True}])
def test_search_canonicalizes_incompatible_tree_sharing(changes):
    config = {**controller.DEFAULT, 'share_fold_preprocessing': True,
              'share_fold_tree': True, 'tree_blend': .5, **changes}
    canonical = controller.canonical_config(config)
    assert canonical['share_fold_tree'] is False
    assert config['share_fold_tree'] is True
    assert controller.canonical_config(canonical) == canonical


def test_search_retains_valid_reuse_and_never_proposes_invalid_dependencies():
    config = controller.canonical_config({**controller.DEFAULT,
        'share_fold_preprocessing': True, 'share_fold_tree': True})
    assert config['share_fold_preprocessing'] and config['share_fold_tree']
    assert controller.DEFAULT['share_fold_preprocessing'] is False
    assert controller.DEFAULT['share_fold_tree'] is False
    for index in range(200):
        proposed, _, _ = controller.propose(index, [])
        assert not proposed['share_fold_tree'] or (proposed['share_fold_preprocessing'] and proposed['tree_blend'])
    assert controller.SPACE['share_fold_preprocessing'] == [False, True]
    assert controller.SPACE['share_fold_tree'] == [False, True]


def test_quality_gate_excludes_runtime_and_ros_but_requires_stability():
    row = {'metrics': {k: {'better': True} for k in controller.QUALITY_KEYS}}
    row['metrics']['run_time_s'] = {'better': False}
    row['metrics']['combined_score'] = {'better': False}
    assert controller.quality_gate(row)
    row['metrics']['f1_boot_std']['better'] = False
    assert not controller.quality_gate(row)
    del row['metrics']['f1_boot_std']
    assert not controller.quality_gate(row)
    assert not controller.quality_gate({})


def test_quality_margin_ignores_runtime_ros_and_rejects_missing_quality():
    row = {'result': {'validity': 1, 'combined_score': 1}, 'comparisons': [{'metrics': {
        key: {'candidate': .9 if key in controller.LOWER else 1.1, 'baseline': 1.0}
        for key in controller.QUALITY_KEYS}}]}
    row['comparisons'][0]['metrics']['run_time_s'] = {'candidate': 99999, 'baseline': 1}
    row['comparisons'][0]['metrics']['combined_score'] = {'candidate': 1, 'baseline': 999}
    assert controller.quality_margin(row) == pytest.approx(.1)
    row['comparisons'][0]['metrics']['f1_boot_std']['candidate'] = 1.2
    assert controller.quality_margin(row) == pytest.approx(-.2)
    del row['comparisons'][0]['metrics']['recall']
    assert controller.quality_margin(row) == -float('inf')


def test_quality_selection_parent_prefers_quality_over_fast_high_score():
    import copy
    good = {'trial': 0, 'config': dict(controller.DEFAULT), 'result': {'validity': 1, 'combined_score': 10},
            'comparisons': [{'metrics': {key: {'candidate': .9 if key in controller.LOWER else 1.1, 'baseline': 1.0}
                                       for key in controller.QUALITY_KEYS}}]}
    fast = copy.deepcopy(good)
    fast['trial'] = 1
    fast['result']['combined_score'] = 100
    fast['comparisons'][0]['metrics']['recall']['candidate'] = .8
    _, parent, _ = controller.propose(9, [good, fast], quality_selection=True)
    assert parent == 0

@pytest.mark.parametrize("members", [False, True])
def test_fractional_focal_has_finite_saturated_gradients_and_matches_formula(members):
    torch = pytest.importorskip("torch")
    c = module("fractional_focal", "experiments/hdd_dl/candidate.py")
    y = torch.tensor([1., 0., 1., 0.], dtype=torch.float64)
    z = torch.tensor([1000., -1000., -1000., 1000.], dtype=torch.float64)
    if members:
        z = z[:, None].repeat(1, 2)
    z.requires_grad_()
    loss = c.training_loss(z, y, torch.ones(4, dtype=torch.float64), torch.tensor(3.), gamma=.25)
    loss.backward()
    assert torch.isfinite(loss) and torch.isfinite(z.grad).all()
    assert z.grad.abs().sum() > 0
    mild = torch.tensor([2., -3., -.7, .2], dtype=torch.float64, requires_grad=True)
    w = torch.tensor([1., 2., 3., 4.], dtype=torch.float64)
    pos = torch.tensor(3., dtype=torch.float64)
    pt = torch.where(y > 0, mild.sigmoid(), 1 - mild.sigmoid())
    expected = (torch.nn.functional.binary_cross_entropy_with_logits(
        mild, y, pos_weight=pos, reduction="none") * (1 - pt).pow(.25) * w).mean()
    actual = c.training_loss(mild, y, w, pos, gamma=.25)
    assert torch.allclose(actual, expected, atol=1e-12)
    assert torch.autograd.gradcheck(lambda v: c.training_loss(v, y, w, pos, gamma=.25), (mild,))

@pytest.mark.parametrize("patience", [2, 5, 10])
@pytest.mark.parametrize("schedule", ["constant", "plateau"])
def test_early_stop_patience_controls_stagnation_and_restores_best(monkeypatch, patience, schedule):
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("GPU candidate")
    import numpy as np
    c = module("hdd_patience", "experiments/hdd_dl/candidate.py")
    rng = np.random.default_rng(77)
    tab = rng.normal(size=(80, 6)).astype("float32")
    seq = rng.normal(size=(80, 4, 14)).astype("float32")
    y = np.tile([0, 1], 40).astype("float32")
    cfg = {**controller.DEFAULT, "width": 16, "depth": 1, "epochs": 20,
           "tree_blend": 0., "early_stop_patience": patience, "train_seconds": 120,
           "lr_schedule": schedule}
    monkeypatch.setattr(c, "average_precision_score", lambda *a, **k: .5)
    details = {}
    q, v = c.fit_one(tab, seq, y, np.ones(80), tab[:7], seq[:7], cfg,
                     np.arange(60), np.arange(60, 80), diagnostics=details)
    assert details["epochs_completed"] == patience + 1
    assert details["best_epoch"] == 0
    expected = [cfg["lr"] * (0.5 ** (max(i - 1, 0) // 4)) if schedule == "plateau"
                else cfg["lr"] for i in range(patience + 1)]
    assert details["learning_rates"] == pytest.approx(expected)
    q0, v0 = c.fit_one(tab, seq, y, np.ones(80), tab[:7], seq[:7],
                       {**cfg, "epochs": 1}, np.arange(60), np.arange(60, 80))
    assert np.allclose(q, q0) and np.allclose(v, v0)

def test_symmetric_context_covers_full_observed_window_and_backpropagates():
    torch = pytest.importorskip("torch")
    c = module("symmetric_context", "experiments/hdd_dl/candidate.py")
    cfg = {**controller.DEFAULT, "family": "tcn", "temporal_context": "symmetric14"}
    net = c.Network(6, 4, cfg)
    for layer in net.conv:
        if isinstance(layer, torch.nn.Conv1d):
            torch.nn.init.constant_(layer.weight, .01)
            torch.nn.init.constant_(layer.bias, .01)
    x = torch.ones(2, 4, 14, requires_grad=True)
    z = net.conv(x)
    assert z.shape == (2, 32, 14)
    z[0, :, 7].sum().backward()
    assert (x.grad[0].abs().sum(dim=0) > 0).all()
    output = net(torch.ones(2, 6), x.detach())
    assert output.shape == (2,) and torch.isfinite(output).all()
    output.sum().backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in net.parameters())
    local = c.Network(6, 4, {**cfg, "temporal_context": "local"})
    assert sum(p.numel() for p in net.parameters()) - sum(p.numel() for p in local.parameters()) == 3104

def test_planner_quality_ranking_preserves_gaps_and_recent_failures():
    planner = module("quality_feedback", "experiments/hdd_dl/planner.py")
    records = [{"trial": i, "config": controller.DEFAULT,
                "result": {**result(), "combined_score": 100-i},
                "comparisons": [{"baseline": "/sensitive/path", "metrics": {
                    "f1": {"candidate": .4, "baseline": .5, "better": False}},
                    "all_quality_strictly_better": False}]} for i in range(16)]
    records[-1]["result"] = {"validity": 0, "error": "not sent externally"}
    feedback = planner.summarize(records, ranking_key=lambda r: -abs(r["trial"] - 7))
    assert {5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15} == {r["trial"] for r in feedback}
    assert feedback[0]["trial"] == 7
    assert feedback[0]["baseline_comparisons"][0]["metrics"]["f1"]["better"] is False
    assert "baseline" not in feedback[0]["baseline_comparisons"][0]
    assert "error" not in feedback[-1]

@pytest.mark.parametrize("family", ["tcn", "dual"])
def test_temporal_flatten_retains_positions_and_trains(family):
    torch = pytest.importorskip("torch")
    c = module("hdd_flatten", "experiments/hdd_dl/candidate.py")
    cfg = {**controller.DEFAULT, "family": family, "temporal_flatten": True}
    net = c.Network(6, 4, cfg)
    seq = torch.randn(3, 4, 14, requires_grad=True)
    tab = torch.randn(3, 6)
    captured = []
    hook = net.input.register_forward_pre_hook(lambda m, args: captured.append(args[0].detach()))
    expected = net.conv(seq).detach().flatten(1)
    output = net(tab, seq)
    hook.remove()
    assert torch.equal(captured[0][:, 6:454], expected)
    assert output.shape == (3,)
    output.sum().backward()
    assert torch.isfinite(seq.grad).all()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in net.parameters())
    with pytest.raises(ValueError, match="14-day"):
        net(tab, seq[:, :, :13])

@pytest.mark.parametrize("overrides", [{"family": "mlp"}, {"temporal_max_pool": True}, {"temporal_attention": True}])
def test_temporal_flatten_rejects_incompatible_pooling(overrides):
    pytest.importorskip("torch")
    c = module("hdd_flatten_invalid", "experiments/hdd_dl/candidate.py")
    with pytest.raises(ValueError, match="temporal_flatten"):
        c.Network(6, 4, {**controller.DEFAULT, "family": "tcn", "temporal_flatten": True, **overrides})

@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_near_optimal_threshold_matches_weighted_realizable_brute_force(seed):
    pytest.importorskip("torch")
    import numpy as np
    c = module("hdd_near_optimal", "experiments/hdd_dl/candidate.py")
    rng = np.random.default_rng(seed)
    y = np.tile([0., 1.], 30)
    p = rng.integers(0, 12, len(y)) / 12
    w = rng.uniform(.1, 5, len(y))
    cuts = sorted(set(p), reverse=True)
    scores = []
    for cut in cuts:
        alarms = p >= cut
        tp = np.sum(w * y * alarms)
        fp = np.sum(w * (1 - y) * alarms)
        scores.append(2 * tp / (tp + fp + np.sum(w * y)))
    eligible = [cut for cut, score in zip(cuts, scores) if score >= .99 * max(scores)]
    expected = eligible[len(eligible) // 2]
    saved = [x.copy() for x in (y, p, w)]
    assert c.calibration_threshold(y, p, w, {"threshold_estimator": "near_optimal_median"}) == expected
    perm = rng.permutation(len(y))
    assert c.calibration_threshold(y[perm], p[perm], w[perm], {"threshold_estimator": "near_optimal_median"}) == expected
    assert all(np.array_equal(a, b) for a, b in zip((y, p, w), saved))

def test_raw_relative_sequence_preserves_growth_resets_and_missingness():
    pytest.importorskip('torch')
    import numpy as np
    c = module('raw_relative', 'experiments/hdd_dl/candidate.py')
    x = np.array([[[np.nan, 1000000, 1000003, np.nan, 2],
                   [np.nan, np.nan, np.nan, np.nan, np.nan],
                   [0, 0, 4, 1, 0]]], dtype=np.float32)
    before = x.copy()
    z = c.relative_change_sequence(x)
    expected = np.array([[[0, 0, np.log(4), 0, -np.log(999999)],
                          [0, 0, 0, 0, 0],
                          [0, 0, np.log(5), np.log(2), 0]]], dtype=np.float32)
    assert np.allclose(z, expected)
    assert np.array_equal(x, before, equal_nan=True)
    assert np.isfinite(z).all()
    extreme = np.array([[[-np.finfo(np.float32).max, np.finfo(np.float32).max]]])
    assert np.isfinite(c.relative_change_sequence(extreme)).all()


def test_raw_relative_feature_integration_preserves_existing_inputs(monkeypatch):
    pytest.importorskip('torch')
    import numpy as np
    import pandas as pd
    c = module('raw_relative_features', 'experiments/hdd_dl/candidate.py')
    index = pd.DataFrame({'serial_number':['a'], 'cutoff_date':['2026-01-14'], 'model':['ST']})
    history = pd.DataFrame({'serial_number':['a']*3,
        'date':['2026-01-14','2026-01-01','2026-01-03'], 'smart_9_raw':[110,100,105]})
    monkeypatch.setattr(c, 'CONFIG', {})
    tab,seq = c.features(history,index,['smart_9_raw'])
    monkeypatch.setattr(c, 'CONFIG', {'sequence_relative_change':True})
    tab1,seq1 = c.features(history,index,['smart_9_raw'])
    assert np.array_equal(tab,tab1)
    assert np.array_equal(seq,seq1[:,:2])
    expected = np.zeros(14); expected[2]=np.log(6); expected[13]=np.log(11)
    assert np.allclose(seq1[0,2],expected)
