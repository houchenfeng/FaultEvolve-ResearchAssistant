"""Contract export must be complete, serialisable and reference-clean."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import export_web_contracts as export  # noqa: E402
from faultevolve.webapi import create_app  # noqa: E402
from faultevolve.webapi.contracts import CONTRACT_MODELS  # noqa: E402


def _iter_refs(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                yield value
            else:
                yield from _iter_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_refs(item)


def test_openapi_is_json_serialisable() -> None:
    schema = create_app().openapi()
    text = json.dumps(schema, ensure_ascii=False)
    assert json.loads(text) == schema


def test_every_dto_is_published_in_components() -> None:
    """A DTO absent from the OpenAPI cannot reach the front-end's types.

    This is the guard for TODO §1.5: the UI must never hand-declare a DTO, so
    every DTO has to be in the contract even before its endpoint exists.
    """
    schemas = create_app().openapi()["components"]["schemas"]
    missing = [m.__name__ for m in CONTRACT_MODELS if m.__name__ not in schemas]
    assert missing == []


def test_no_unexpanded_defs_and_no_dangling_refs() -> None:
    schema = create_app().openapi()
    schemas = schema["components"]["schemas"]

    with_defs = [name for name, body in schemas.items() if "$defs" in body]
    assert with_defs == []

    dangling = sorted({ref for ref in _iter_refs(schema)
                       if ref.split("/")[-1] not in schemas})
    assert dangling == []


def test_export_writes_the_four_declared_files() -> None:
    produced = export.build_all()
    assert sorted(produced) == sorted(name for name, _ in export.CONTRACT_FILES)
    for name, text in produced.items():
        assert text.endswith("\n"), f"{name} must end with a newline"
        json.loads(text)


def test_committed_contract_files_exist() -> None:
    for name, _ in export.CONTRACT_FILES:
        assert (export.OPENAPI_DIR / name).is_file(), f"web/openapi/{name} is missing"


def test_writer_emits_lf_not_crlf() -> None:
    """The writer must not translate newlines itself.

    core.autocrlf=true rewrites the worktree copy on checkout, but that is git's
    doing; the file this script writes -- and hence the blob -- stays LF.
    """
    produced = export.build_all()
    for name, text in produced.items():
        assert "\r" not in text, f"{name} contains a carriage return"
