"""SEARCH/REPLACE patch parsing and application."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from faultevolve.optimization.candidate_spec import source_hash as compute_source_hash

source_hash = compute_source_hash

_HUNK_RE = re.compile(
    r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE",
    re.DOTALL,
)
_PATCH_RE = re.compile(
    r"<patch\s+parent_hash=\"([^\"]+)\"\s+module=\"([^\"]+)\">(.*?)</patch>",
    re.DOTALL,
)


class PatchRejectReason(str, Enum):
    PARSE_ERROR = "parse_error"
    UNSUPPORTED_FORMAT = "unsupported_format"
    PARENT_HASH_MISMATCH = "parent_hash_mismatch"
    NO_MATCH = "no_match"
    MULTIPLE_MATCH = "multiple_match"
    OUT_OF_BLOCK = "out_of_block"
    MULTI_MODULE = "multi_module"
    PROTECTED_MARKER_EDIT = "protected_marker_edit"
    TOO_MANY_HUNKS = "too_many_hunks"
    TOO_LARGE = "too_large"
    SYNTAX_ERROR = "syntax_error"
    STATIC_RULE_VIOLATION = "static_rule_violation"
    EMPTY_SEARCH = "empty_search"
    OVERLAP = "overlap"


@dataclass(frozen=True)
class Hunk:
    search: str
    replace: str


@dataclass(frozen=True)
class Patch:
    parent_hash: str
    module: str
    hunks: list[Hunk]


@dataclass(frozen=True)
class PatchResult:
    ok: bool
    code: str | None
    reason: PatchRejectReason | None
    detail: str
    module: str | None
    changed_lines: int


def module_spans(code: str) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    lines = code.splitlines(keepends=True)
    open_module: str | None = None
    start = 0
    offset = 0
    for line in lines:
        m_begin = re.match(r"# FE-BLOCK-BEGIN (\w+)", line.strip())
        m_end = re.match(r"# FE-BLOCK-END (\w+)", line.strip())
        if m_begin:
            open_module = m_begin.group(1)
            start = offset
        elif m_end and open_module == m_end.group(1):
            spans[open_module] = (start, offset + len(line))
            open_module = None
        offset += len(line)
    return spans


def parse_patch(response: str) -> Patch | PatchResult:
    if "---" in response and "+++" in response:
        return PatchResult(
            ok=False,
            code=None,
            reason=PatchRejectReason.UNSUPPORTED_FORMAT,
            detail="unified diff not supported",
            module=None,
            changed_lines=0,
        )
    match = _PATCH_RE.search(response)
    if not match:
        return PatchResult(
            ok=False,
            code=None,
            reason=PatchRejectReason.PARSE_ERROR,
            detail="missing patch block",
            module=None,
            changed_lines=0,
        )
    parent_hash, module, body = match.group(1), match.group(2), match.group(3)
    hunks: list[Hunk] = []
    for sm in _HUNK_RE.finditer(body):
        hunks.append(Hunk(search=sm.group(1), replace=sm.group(2)))
    if not hunks:
        return PatchResult(
            ok=False,
            code=None,
            reason=PatchRejectReason.PARSE_ERROR,
            detail="no hunks",
            module=module,
            changed_lines=0,
        )
    return Patch(parent_hash=parent_hash, module=module, hunks=hunks)


def apply_patch(
    parent_code: str,
    patch: Patch,
    *,
    static_check: Callable[[str], str],
    max_hunks: int,
    max_changed_lines: int,
) -> PatchResult:
    if compute_source_hash(parent_code) != patch.parent_hash:
        return PatchResult(
            ok=False,
            code=None,
            reason=PatchRejectReason.PARENT_HASH_MISMATCH,
            detail="parent hash mismatch",
            module=patch.module,
            changed_lines=0,
        )
    spans = module_spans(parent_code)
    if patch.module not in spans:
        return PatchResult(
            ok=False,
            code=None,
            reason=PatchRejectReason.OUT_OF_BLOCK,
            detail="module markers missing",
            module=patch.module,
            changed_lines=0,
        )
    if len(patch.hunks) > max_hunks:
        return PatchResult(
            ok=False,
            code=None,
            reason=PatchRejectReason.TOO_MANY_HUNKS,
            detail="too many hunks",
            module=patch.module,
            changed_lines=0,
        )
    mod_start, mod_end = spans[patch.module]
    code = parent_code
    ranges: list[tuple[int, int]] = []
    changed_lines = 0
    for hunk in patch.hunks:
        if not hunk.search:
            return PatchResult(
                ok=False,
                code=None,
                reason=PatchRejectReason.EMPTY_SEARCH,
                detail="empty search",
                module=patch.module,
                changed_lines=0,
            )
        if "FE-BLOCK" in hunk.replace:
            return PatchResult(
                ok=False,
                code=None,
                reason=PatchRejectReason.PROTECTED_MARKER_EDIT,
                detail="marker edit",
                module=patch.module,
                changed_lines=0,
            )
        norm_parent = code.replace("\r\n", "\n")
        norm_search = hunk.search.replace("\r\n", "\n")
        count = norm_parent.count(norm_search)
        if count == 0:
            return PatchResult(
                ok=False,
                code=None,
                reason=PatchRejectReason.NO_MATCH,
                detail="search not found",
                module=patch.module,
                changed_lines=0,
            )
        if count > 1:
            return PatchResult(
                ok=False,
                code=None,
                reason=PatchRejectReason.MULTIPLE_MATCH,
                detail="search matched multiple times",
                module=patch.module,
                changed_lines=0,
            )
        idx = norm_parent.index(norm_search)
        end = idx + len(norm_search)
        if idx < mod_start or end > mod_end:
            return PatchResult(
                ok=False,
                code=None,
                reason=PatchRejectReason.OUT_OF_BLOCK,
                detail="match outside module block",
                module=patch.module,
                changed_lines=0,
            )
        ranges.append((idx, end))
        changed_lines += abs(len(hunk.replace.splitlines()) - len(hunk.search.splitlines()))
        code = norm_parent[:idx] + hunk.replace + norm_parent[end:]
    ranges.sort()
    for i in range(1, len(ranges)):
        if ranges[i][0] < ranges[i - 1][1]:
            return PatchResult(
                ok=False,
                code=None,
                reason=PatchRejectReason.OVERLAP,
                detail="overlapping hunks",
                module=patch.module,
                changed_lines=0,
            )
    if changed_lines > max_changed_lines:
        return PatchResult(
            ok=False,
            code=None,
            reason=PatchRejectReason.TOO_LARGE,
            detail="too many changed lines",
            module=patch.module,
            changed_lines=changed_lines,
        )
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return PatchResult(
            ok=False,
            code=None,
            reason=PatchRejectReason.SYNTAX_ERROR,
            detail=str(exc),
            module=patch.module,
            changed_lines=changed_lines,
        )
    static_err = static_check(code)
    if static_err:
        return PatchResult(
            ok=False,
            code=None,
            reason=PatchRejectReason.STATIC_RULE_VIOLATION,
            detail=static_err,
            module=patch.module,
            changed_lines=changed_lines,
        )
    return PatchResult(
        ok=True,
        code=code,
        reason=None,
        detail="ok",
        module=patch.module,
        changed_lines=changed_lines,
    )
