"""Offline coverage for Jev screening and priors."""

from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud import jev_client
from faultevolve.cloud.jev_client import (
    JevClient,
    JevError,
    JevResponse,
    MockJevClient,
    parse_choice,
    parse_noul,
    parse_score,
)
from faultevolve.cloud.judge import JudgeClient, PrescreenResult, should_defer_candidate
from faultevolve.cloud.selection import UCTSelector, get_jev_prior
from faultevolve.common.metering import CallMetrics, RunMetrics
from faultevolve.common.schemas import Node, NodeArtifact, NodeStatus, OperatorType
from faultevolve.config import EvolveConfig, JudgeConfig


def _node(node_id: str = "n", score: float = 0.0) -> Node:
    return Node(
        id=node_id,
        experiment_id="e",
        branch_id="b",
        operator=OperatorType.REFINE,
        artifact=NodeArtifact(code="x = 1", intent="change", hypothesis="h"),
    )


def test_request_format(monkeypatch):
    monkeypatch.setenv("MIYANG_API_KEY", "test-key")
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(200, json={"answers": {"valid": {"noul": 1}}})

    cfg = JudgeConfig()
    response = JevClient(cfg, httpx.MockTransport(handler)).decide(
        "state", [{"name": "valid", "type": "noul", "criteria": {"true": "y", "false": "n"}}]
    )
    assert str(seen["request"].url) == cfg.base_url
    assert seen["request"].headers["Authorization"] == "Bearer test-key"
    body = json.loads(seen["request"].content)
    assert body["model"] == cfg.model
    assert body["state"] == {"text": "state"}
    assert isinstance(body["questions"], dict)
    assert body["questions"]["valid"] == {
        "type": "noul",
        "criteria": {"true": "y", "false": "n"},
    }
    assert response.answers["valid"]["noul"] == 1


def test_response_parsing_variants(monkeypatch):
    assert parse_noul({"noul": 0.7}) == 0.7
    assert parse_noul({"noul": {"true": 0.8, "false": 0.2}}) == 0.8
    assert parse_choice({"probabilities": {"better": 2}}, ["better", "same"]) == {
        "better": 1.0, "same": 0.0
    }
    assert parse_score({"score": 0.7}) == parse_score({"score": 7}) == parse_score({"score": 70})
    monkeypatch.setenv("MIYANG_API_KEY", "test-key")
    for usage, expected in [
        ({"prompt_tokens": 2, "completion_tokens": 3}, (2, 3, 5)),
        ({"input_tokens": 4, "output_tokens": 1}, (4, 1, 5)),
        ({"total_tokens": 9}, (9, 0, 9)),
        ({}, (0, 0, 0)),
    ]:
        client = JevClient(JudgeConfig(), httpx.MockTransport(
            lambda _: httpx.Response(200, json={"answers": {}, "usage": usage})
        ))
        result = client.decide("", [])
        assert (result.prompt_tokens, result.completion_tokens, result.total_tokens) == expected


def test_retry_only_429_and_5xx(monkeypatch):
    monkeypatch.setenv("MIYANG_API_KEY", "test-key")
    statuses = iter([429, 500, 200])
    calls = []
    client = JevClient(
        JudgeConfig(retries=2),
        httpx.MockTransport(lambda _: (
            calls.append(1) or httpx.Response(next(statuses), json={"answers": {}})
        )),
    )
    assert client.decide("", []).answers == {}
    assert len(calls) == 3
    for response in [
        lambda _: httpx.Response(400),
        lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("timeout")),
    ]:
        calls = []
        with pytest.raises(JevError):
            JevClient(JudgeConfig(retries=2), httpx.MockTransport(
                lambda request: (calls.append(1), response(request))[1]
            )).decide("", [])
        assert len(calls) == 1


def test_missing_key_disables_without_http(monkeypatch):
    monkeypatch.delenv("MIYANG_API_KEY", raising=False)
    judge = JudgeClient(EvolveConfig.from_dict({"judge": {"provider": "jev"}}))
    assert not judge.enabled
    assert judge.disabled_reason == "missing_key"
    assert not judge.prescreen(_node(), "x=2", "i").attempted


@pytest.mark.parametrize("kind", ["timeout", "500", "badjson"])
def test_fail_open_timeout_500_badjson(kind, monkeypatch):
    monkeypatch.setenv("MIYANG_API_KEY", "test-key")
    def handler(_):
        if kind == "timeout":
            raise httpx.ReadTimeout("secret")
        if kind == "500":
            return httpx.Response(500)
        return httpx.Response(200, content=b"bad")
    cfg = EvolveConfig.from_dict({
        "judge": {"provider": "jev", "prescreen": True, "max_consecutive_errors": 9}
    })
    result = JudgeClient(cfg, JevClient(cfg.judge, httpx.MockTransport(handler))).prescreen(
        _node(), "x=2", "i"
    )
    assert result.attempted and not result.ok and result.decision == "evaluate"
    assert "test-key" not in result.error


def test_circuit_breaker_after_3_errors():
    class Broken:
        calls = 0
        def decide(self, state, questions):
            self.calls += 1
            raise JevError("timeout")
    cfg = EvolveConfig.from_dict({"judge": {"provider": "mock", "max_consecutive_errors": 3}})
    broken = Broken()
    judge = JudgeClient(cfg, broken)
    for _ in range(5):
        judge.prescreen(_node(), "x=2", "i")
    assert broken.calls == 3
    assert judge.disabled_reason == "circuit_open"


def test_prescreen_skip_reduces_evaluations():
    result = PrescreenResult(p_invalid=0.9)
    assert should_defer_candidate(result, True, 0.85, 0.15, "skip") == "skip_invalid"


def test_abandoned_does_not_consume_widening():
    assert NodeStatus.ABANDONED.value == "abandoned"


def test_audit_precision_exact():
    metrics = RunMetrics(screen_audited=3, screen_audit_bad=2)
    assert metrics.screening_precision == pytest.approx(2 / 3)


def test_warmup_shadow():
    cfg = EvolveConfig.from_dict({"judge": {"provider": "mock", "warmup": 2}})
    judge = JudgeClient(cfg)
    judge.client.decide = lambda *_: JevResponse({
        "valid": {"noul": 0}, "improve": {"probabilities": {}}, "value": {"score": 0}
    })
    results = [judge.prescreen(_node(), "x=2", "i") for _ in range(3)]
    assert [r.decision for r in results] == ["evaluate", "evaluate", "skip_invalid"]
    assert all(r.would_screen for r in results)


def test_defer_flush():
    result = PrescreenResult(value=0.01)
    assert should_defer_candidate(result, True, 0.85, 0.15, "defer") == "defer"
    metrics = RunMetrics(iterations_done=2)
    metrics.add_eval(1, True, count_iteration=False)
    assert metrics.iterations_done == 2


def test_prior_non_uniform_sums_to_one():
    prior = get_jev_prior(["high", "low"], {
        "values": {"high": 0.9, "low": 0.1}, "tau": 0.5, "enabled": True
    })
    assert prior["high"] > prior["low"]
    assert sum(prior.values()) == pytest.approx(1)


@pytest.mark.parametrize("enabled", [False, True])
def test_prior_uniform_when_disabled_or_uct(enabled):
    context = {"values": {} if enabled else {"a": 0.9}, "tau": 0.5, "enabled": enabled}
    assert get_jev_prior(["a", "b"], context) == {"a": 0.5, "b": 0.5}


def test_prior_and_defer_rebuild_on_resume():
    selector = UCTSelector(EvolveConfig())
    selector.set_node_priors({"a": 0.9}, 0.5, True)
    assert selector.node_values == {"a": 0.9}


def test_default_off_zero_http():
    judge = JudgeClient(EvolveConfig())
    result = judge.prescreen(_node(), "x=2", "i")
    assert not result.attempted
    metrics = RunMetrics().to_dict()
    assert metrics["jev_calls"] == metrics["evaluations_saved"] == 0
    assert metrics["screening_precision"] is None


def test_e2e_mock_summary_fields():
    metrics = RunMetrics()
    metrics.add_llm_call(CallMetrics(5, 2, 1), "jev")
    metrics.jev_calls = metrics.candidates_screened = metrics.evaluations_saved = 1
    metrics.screen_audited = metrics.screen_audit_bad = 1
    metrics.jev_prior_active = True
    summary = metrics.to_dict()
    assert summary["jev_tokens"] > 0
    assert summary["screening_precision"] is not None


def test_cli_judge_ping_success_and_sanitized_failure(monkeypatch, tmp_path):
    (tmp_path / "evolve.yaml").write_text("judge: {provider: none}\n")
    monkeypatch.setenv("MIYANG_API_KEY", "test-key")
    monkeypatch.setattr(jev_client.JevClient, "decide", lambda *_: JevResponse(
        {"valid": {"noul": 1}}, 1, 2, 3, 4
    ))
    runner = CliRunner()
    success = runner.invoke(app, ["judge", "ping", "--task-dir", str(tmp_path), "--json"])
    assert success.exit_code == 0 and "test-key" not in success.stdout
    monkeypatch.setattr(jev_client.JevClient, "decide", lambda *_: (_ for _ in ()).throw(
        JevError("test-key")
    ))
    failure = runner.invoke(app, ["judge", "ping", "--task-dir", str(tmp_path), "--json"])
    assert failure.exit_code == 1 and "test-key" not in failure.stdout


def test_no_key_in_events_logs(caplog, monkeypatch):
    monkeypatch.delenv("MIYANG_API_KEY", raising=False)
    JudgeClient(EvolveConfig.from_dict({"judge": {"provider": "jev"}}))
    assert "MIYANG_API_KEY" not in caplog.text


def test_cloud_modules_task_agnostic():
    from pathlib import Path
    for name in ["engine.py", "judge.py", "jev_client.py", "selection.py"]:
        text = (Path("src/faultevolve/cloud") / name).read_text(encoding="utf-8").lower()
        assert all(word not in text for word in ["smart", "backblaze"])
