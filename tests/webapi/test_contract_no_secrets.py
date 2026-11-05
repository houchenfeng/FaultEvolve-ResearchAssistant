"""The exported contract must never carry a secret or a host path (TODO §12.4 E2E-05)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import export_web_contracts as export  # noqa: E402

#: Env vars whose *values* must never appear. Their *names* may appear, because
#: ``api_key_env`` legitimately defaults to the name of the variable to read.
SECRET_ENV_VARS = ("DASHSCOPE_API_KEY", "MIYANG_API_KEY", "FE_API_KEY")

ABS_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:[A-Za-z]:\\[^\\/:*?\"<>|\r\n]+(?:\\[^\\/:*?\"<>|\r\n]*)*"
    r"|/(?:home|root|mnt|media|Users|var|opt|srv|etc)(?:/[^\s\"']*)?)"
)


def test_secret_values_never_reach_the_contract(monkeypatch) -> None:
    sentinel = "sk-CONTRACTPROBE0123456789abcdef"
    for var in SECRET_ENV_VARS:
        monkeypatch.setenv(var, sentinel)

    for name, text in export.build_all().items():
        assert sentinel not in text, f"{name} leaked a secret value"
        assert "CONTRACTPROBE" not in text, f"{name} leaked a secret value"


def test_contract_contains_no_absolute_host_path() -> None:
    for name, text in export.build_all().items():
        hits = ABS_PATH_RE.findall(text)
        assert hits == [], f"{name} contains absolute paths: {hits[:3]}"


def test_contract_never_mentions_holdout() -> None:
    for name, text in export.build_all().items():
        assert "holdout" not in text.lower(), f"{name} mentions holdout"


def test_api_key_env_names_are_allowed_but_marked_as_names() -> None:
    """Guards the intent of the rule above, so nobody "fixes" it by renaming.

    ``JudgeConfig.api_key_env`` is the name of an env var, which is config, not
    a secret. This test pins that distinction.
    """
    catalog = export.build_all()["evolve-config.schema.json"]
    assert "api_key_env" in catalog
    assert "sk-" not in catalog


#: Field names that must never appear as a *value-carrying* DTO field. A secret
#: travelling to the browser is the one mistake the whole masking design exists
#: to prevent (TODO 4.3: "私钥路径和密码不返回浏览器").
#:
#: Bare ``token`` is deliberately *not* in this pattern: the contract is full of
#: LLM token **counts** (``total_tokens``, ``knowledge_tokens``...). Only
#: credential-shaped names belong here.
DANGEROUS_FIELD_RE = re.compile(
    r"(password|passwd|private_key|api_key|credential|secret"
    r"|access_token|auth_token|bearer_token|api_token)",
    re.IGNORECASE,
)


def _iter_component_properties() -> list[tuple[str, str, dict]]:
    """``(schema_name, property_name, property_schema)`` for every DTO field."""
    import json

    document = json.loads(export.build_all()["faultevolve.openapi.json"])
    found: list[tuple[str, str, dict]] = []
    for schema_name, schema in document.get("components", {}).get("schemas", {}).items():
        for prop_name, prop_schema in (schema or {}).get("properties", {}).items():
            found.append((schema_name, prop_name, prop_schema or {}))
    return found


def test_no_dto_carries_a_secret_as_a_value() -> None:
    """A secret-looking field name is only allowed when it is a *flag*.

    Two escape hatches, both narrow on purpose:

    * the value is a ``boolean`` -- i.e. "is it configured?" / "is it masked?",
      which is exactly what ``ServerProfileResponse`` exposes;
    * the name ends in ``_ref`` -- a *reference* the server resolves locally,
      which is what ``ServerProfileRequest.private_key_ref`` is.

    Anything else (a plain ``password`` or ``private_key`` string) fails here.
    """
    offenders: list[str] = []
    for schema_name, prop_name, prop_schema in _iter_component_properties():
        if not DANGEROUS_FIELD_RE.search(prop_name):
            continue
        is_flag = prop_schema.get("type") == "boolean"
        is_ref = prop_name.lower().endswith("_ref")
        if not (is_flag or is_ref):
            offenders.append(f"{schema_name}.{prop_name} ({prop_schema.get('type')})")

    assert offenders == [], f"secret-carrying DTO fields: {offenders}"


def test_server_profile_response_masks_instead_of_echoing() -> None:
    """The one DTO that touches credentials advertises only booleans."""
    import json

    document = json.loads(export.build_all()["faultevolve.openapi.json"])
    schema = document["components"]["schemas"]["ServerProfileResponse"]
    props = schema["properties"]

    for flag in ("has_private_key", "secret_masked"):
        assert props[flag]["type"] == "boolean", f"{flag} must be a boolean flag"

    # The request side takes a reference, never the key itself.
    request_props = document["components"]["schemas"]["ServerProfileRequest"]["properties"]
    assert "private_key_ref" in request_props
    for forbidden in ("private_key", "password", "passphrase"):
        assert forbidden not in request_props, f"request must not accept {forbidden}"
