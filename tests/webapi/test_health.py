"""``/api/health`` and ``/api/meta`` must stay free of environment detail."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from faultevolve.webapi.app import create_app  # noqa: E402
from faultevolve.webapi.contracts import CONTRACT_VERSION  # noqa: E402
from faultevolve.webapi.settings import WebSettings  # noqa: E402


def test_health_is_liveness_only(client: TestClient) -> None:
    """The probe reports status and contract version; nothing else."""
    response = client.get("/api/health")
    assert response.status_code == 200
    # Read off the constant, not a literal: a version bump is a contract event
    # and must not require hunting down hard-coded copies of it in tests.
    assert response.json() == {"status": "ok", "contract_version": CONTRACT_VERSION}


def test_health_leaks_no_path_or_key(client: TestClient, fixture_runs_root: Path) -> None:
    """Neither the configured root nor a key name may appear in the body."""
    body = client.get("/api/health").text
    assert str(fixture_runs_root) not in body
    assert "api_key" not in body.lower()
    assert "sk-" not in body


def test_meta_reports_process_control_off_by_default(client: TestClient) -> None:
    """P0 must not advertise a capability the engine does not have yet.

    Phase 4 (decision D-D) flipped ``local_cloud`` to available -- the local
    execution backend really can probe and check paths. Process control stays
    off until phase 7: that is the honest boundary of this build.
    """
    body = client.get("/api/meta").json()
    assert body["process_control_enabled"] is False
    assert body["stream_transport"] == "sse"
    availability = {mode["mode"]: mode["available"] for mode in body["deployment_modes"]}
    assert availability["local_cloud"] is True
    assert availability["local_desktop"] is False


def test_meta_availability_is_derived_not_wished(client: TestClient) -> None:
    """A mode is available exactly when its backend exists in this build.

    Replaces the phase-1 pin ("no mode available"): local_cloud is delivered,
    ssh_cloud mirrors whether asyncssh imports, local_desktop stays P2+.
    """
    from faultevolve.webapi import server_profiles

    body = client.get("/api/meta").json()
    by_mode = {mode["mode"]: mode for mode in body["deployment_modes"]}
    assert by_mode["local_cloud"]["available"] is True
    assert by_mode["local_cloud"]["detail"] == "本机/同机云端执行目标可用"
    assert by_mode["ssh_cloud"]["available"] is server_profiles.ssh_available()
    assert by_mode["local_desktop"]["available"] is False
    # Every entry still carries a human-readable reason, available or not.
    assert all(mode["detail"] for mode in body["deployment_modes"])


def test_meta_process_control_flag_follows_settings(fixture_runs_root: Path) -> None:
    """Turning the flag on is the only thing that changes the report."""
    settings = WebSettings(
        runs_root=fixture_runs_root,
        allowed_path_roots=[fixture_runs_root],
        enable_process_control=True,
    )
    body = TestClient(create_app(settings)).get("/api/meta").json()
    assert body["process_control_enabled"] is True


def test_unmatched_route_returns_a_localised_envelope(client: TestClient) -> None:
    """A 404 must use the shared envelope, not the framework's English detail."""
    response = client.get("/api/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "not_found"
    assert body["message"] == "没有这个接口"
    assert "Not Found" not in response.text


def test_meta_qwen_configured_is_presence_only(
    client: TestClient, monkeypatch
) -> None:
    """The flag follows the env var and the response never contains its value."""
    secret = "sk-qwen-probe-not-for-the-wire"
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    def fail_if_called() -> bool:
        raise AssertionError("Qwen was probed without a key")

    monkeypatch.setattr(
        "faultevolve.webapi.qwen_status.probe_qwen", fail_if_called
    )
    body = client.get("/api/meta").json()
    assert body["qwen_configured"] is False
    assert body["qwen_reachable"] is None

    monkeypatch.setenv("DASHSCOPE_API_KEY", "   ")
    body = client.get("/api/meta").json()
    assert body["qwen_configured"] is False
    assert body["qwen_reachable"] is None

    monkeypatch.setenv("DASHSCOPE_API_KEY", secret)
    monkeypatch.setattr(
        "faultevolve.webapi.qwen_status.probe_qwen", lambda: False
    )
    response = client.get("/api/meta")
    assert response.json()["qwen_configured"] is True
    assert response.json()["qwen_reachable"] is False
    assert secret not in response.text


def test_meta_qwen_reachable_follows_models_probe(
    client: TestClient, monkeypatch
) -> None:
    """A successful probe is reported without copying the key into the body."""
    secret = "sk-qwen-probe-not-for-the-wire"
    monkeypatch.setenv("DASHSCOPE_API_KEY", secret)
    monkeypatch.setattr("faultevolve.webapi.qwen_status.probe_qwen", lambda: True)
    response = client.get("/api/meta")
    body = response.json()
    assert body["qwen_configured"] is True
    assert body["qwen_reachable"] is True
    assert secret not in response.text


def test_wrong_method_is_reported_distinctly(client: TestClient) -> None:
    """POST to a read-only endpoint is 405, not 404."""
    # ``/api/tasks`` is the read-only listing; ``/api/runs`` gained a POST in
    # phase 7, so it can no longer carry this assertion.
    response = client.post("/api/tasks")
    assert response.status_code == 405
    assert response.json()["error_code"] == "method_not_allowed"
