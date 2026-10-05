"""Identifier validation and safe path joining (TODO §2.3 / §2.5).

Two independent gates guard every filesystem access:

1. the identifier must match a strict character whitelist, so no id can ever
   contain a separator, a drive letter or an escape sequence;
2. the joined path is resolved and re-checked against
   :meth:`WebSettings.ensure_allowed`.

Both are needed. The regex is what makes ``..`` unrepresentable; the allow-list
is what stops a *correctly shaped* id from landing outside the run roots. Relying
on either alone would be one mistake away from a traversal bug.

Nothing here returns an unresolved path: callers get the resolved one, so they
cannot accidentally keep using the raw join.
"""

from __future__ import annotations

import re
from pathlib import Path

from faultevolve.webapi.errors import InvalidIdentifierError, RunNotFoundError
from faultevolve.webapi.settings import PathNotAllowedError, WebSettings

#: Allowed identifier shape. Stricter than the filesystem, on purpose:
#: no ``/``, no ``\``, no ``:``, no NUL, no leading dot, max 64 chars.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: Sub-sequences that are refused even though the pattern above would allow
#: them. ``..`` cannot traverse on its own (separators are impossible), but
#: refusing it keeps the intent obvious to the next reader.
_ID_FORBIDDEN = ("..",)


def validate_id(value: str, *, kind: str, field: str | None = None) -> str:
    """Return ``value`` if it is a safe identifier, else raise.

    Args:
        value: the raw path parameter, exactly as it arrived.
        kind: human-readable identifier kind, used in the error detail.
        field: the request field name, for form-level UI highlighting.
    """
    if not isinstance(value, str) or not value:
        raise InvalidIdentifierError(kind, field=field)
    if not _ID_PATTERN.match(value):
        raise InvalidIdentifierError(kind, field=field)
    if any(bad in value for bad in _ID_FORBIDDEN):
        raise InvalidIdentifierError(kind, field=field)
    return value


def is_valid_id(value: str) -> bool:
    """Non-raising variant, for filtering directory listings."""
    try:
        validate_id(value, kind="id")
    except InvalidIdentifierError:
        return False
    return True


def run_roots(settings: WebSettings) -> list[Path]:
    """Every root a run directory may live under, resolved and de-duplicated.

    ``runs_root`` and ``artifacts_root`` are both accepted because the engine
    writes runs under ``.fe/runs`` while the UI also exposes a separate artifact
    root; either may be configured alone.
    """
    roots: list[Path] = []
    for candidate in (settings.runs_root, settings.artifacts_root):
        if candidate is None:
            continue
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def resolve_run_dir(settings: WebSettings, run_id: str) -> Path:
    """Resolve the directory of one run, or raise ``RunNotFoundError``.

    The lookup is a *scan of the immediate children* of each root, not a join:
    the directory that is returned is one the server itself discovered. An id
    therefore cannot name a path the server has not already seen.
    """
    validate_id(run_id, kind="run_id", field="run_id")
    for root in run_roots(settings):
        candidate = root / run_id
        if not settings.is_allowed(candidate):
            continue
        if candidate.is_dir():
            return candidate.resolve()
    raise RunNotFoundError(run_id)


def resolve_run_child(run_dir: Path, *parts: str) -> Path:
    """Join validated names onto an already-resolved run directory.

    ``parts`` are literals supplied by the server (``"programs"``, ``"tree.json"``)
    or identifiers that already passed :func:`validate_id`. The result is
    resolved and asserted to stay inside ``run_dir`` as a second gate.
    """
    candidate = run_dir
    for part in parts:
        # ``Path("..").name`` is not reliably ``""`` across Python versions, so
        # the dot segments are refused explicitly rather than by inference.
        if not part or part in (".", "..") or Path(part).name != part:
            raise InvalidIdentifierError("path segment")
        candidate = candidate / part
    resolved = candidate.resolve()
    if resolved != run_dir and run_dir not in resolved.parents:
        raise PathNotAllowedError(resolved)
    return resolved


def list_run_ids(settings: WebSettings) -> list[str]:
    """Run ids found one level below each root, sorted for stable output.

    Only the immediate children are scanned (TODO §2.4): no recursion, so a
    stray nested directory can never be mistaken for a run.
    """
    found: list[str] = []
    for root in run_roots(settings):
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            name = child.name
            if not is_valid_id(name) or name in found:
                continue
            found.append(name)
    return sorted(found)
