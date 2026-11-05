"""Where runs actually live on a server (TODO D6.1 / D6.2).

The first version of this layer assumed one level: a run directory was a direct
child of a configured root, and its database sat next to its artifacts. A real
NAS layout is neither -- ``/vol/evolve/2026-10/batch-3/<run_id>/`` is normal, and
the engine happily writes ``fe.db`` under ``--runs-dir`` while artifacts go to a
separate ``--artifacts-dir``. Listing a run and then failing to find its files is
the exact defect D6.1 item 4 forbids, so discovery and path pairing live in one
place here.

What this module promises:

* **bounded, non-following scan.** Each root is walked to ``discovery_max_depth``
  levels; a symlinked directory is recorded and skipped, so a link loop cannot
  hang a request.
* **a run is what its files say it is.** A directory becomes a run only when it
  holds a recognised artifact -- never because of its name.
* **origin is evidence, not a guess.** A directory under a configured fixture root
  is a fixture and leaves the product listing. A run this service started itself is
  real (its registry row is the evidence). Anything else is *unverified* and says
  so -- it is never silently presented as a confirmed real run, and never dropped
  without a count.
* **scan errors are data.** An unreadable subdirectory is recorded in the error
  manifest with its relative path and reason; the listing still returns.
* **the counts reconcile.** ``scanned`` (run-shaped directories found), ``paired``
  (directories merged into another), ``listed`` and ``excluded_fixtures`` satisfy
  ``scanned == len(locations) + paired`` and
  ``len(locations) == listed + excluded_fixtures``.

Nothing here opens a database or reads task data: the scan looks at names only.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from faultevolve.webapi.settings import WebSettings

#: Files or directories that make a directory a run directory. ``.fe`` and the
#: data roots are not in this list, and no marker is a substring match.
RUN_MARKERS = (
    "run_summary.json",
    "tree.json",
    "events.jsonl",
    "fe.db",
    "programs",
    "logs",
    "discovery",
    "reports",
    "hpo",
    "workflow.json",
    "hyperparameters",
)

#: Markers that say "this directory is the report half of a run".
REPORT_MARKERS = tuple(name for name in RUN_MARKERS if name != "fe.db")

#: How far below a root the scan may go before it stops looking. A NAS archive is
#: a tree of dates and batches; an unbounded walk would make list latency
#: proportional to the whole volume.
DEFAULT_MAX_DEPTH = 4

#: Hard ceiling on directories visited in one scan, so a misconfigured root (a
#: home directory, say) cannot turn a list call into an hours-long crawl.
MAX_VISITS = 20_000

#: The error manifest is capped: a root with ten thousand unreadable siblings
#: would otherwise dominate the reply. The cap is reported, not hidden.
MAX_ERRORS = 200

ORIGIN_REAL = "real"
ORIGIN_FIXTURE = "fixture"
ORIGIN_UNVERIFIED = "unverified"

TYPE_EVOLVE = "evolve"
TYPE_DISCOVERY = "discovery"
TYPE_AUTOTUNE = "autotune"
TYPE_DATABASE = "database"
TYPE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class ScanError:
    """One directory the scan could not descend into."""

    relative_path: str
    reason: str


@dataclass(frozen=True)
class RunLocation:
    """Where one run's files are, as the server found them.

    ``artifacts_dir`` and ``db_dir`` may differ: that is the whole point of the
    pairing. Either may be ``None`` when only one root holds this run.
    """

    run_id: str
    external_id: str
    source_root: Path
    relative_path: str
    artifacts_dir: Path | None
    db_dir: Path | None
    run_type: str
    origin: str
    readable: bool
    markers: tuple[str, ...] = ()
    failure: str = ""

    @property
    def report_dir(self) -> Path | None:
        """The directory the replay endpoints read their json files from."""
        return self.artifacts_dir or self.db_dir


@dataclass
class ScanOutcome:
    """Locations plus the counts that have to reconcile (TODO D6.2)."""

    locations: list[RunLocation] = field(default_factory=list)
    errors: list[ScanError] = field(default_factory=list)
    scanned: int = 0
    paired: int = 0
    listed: int = 0
    excluded_fixtures: int = 0
    unverified: int = 0
    errors_truncated: bool = False

    def by_external_id(self) -> dict[str, RunLocation]:
        return {location.external_id: location for location in self.locations}

    def by_run_id(self) -> dict[str, list[RunLocation]]:
        """Every location sharing a run id, in scan order.

        A list, not a single entry: two directories may legitimately hold the
        same id, and TODO D6.2 forbids letting one overwrite the other.
        """
        out: dict[str, list[RunLocation]] = {}
        for location in self.locations:
            out.setdefault(location.run_id, []).append(location)
        return out


def _external_id(run_id: str, relative_path: str) -> str:
    """A stable id for a run whose name is already taken in another directory.

    The suffix is a digest of the *relative* path, so the same directory layout
    gives the same id across restarts, and the original run id is preserved in
    ``RunLocation.run_id``.
    """
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:8]
    return f"{run_id}-{digest}"


def _markers(path: Path) -> tuple[str, ...]:
    try:
        names = {entry.name for entry in path.iterdir()}
    except OSError:
        return ()
    return tuple(marker for marker in RUN_MARKERS if marker in names)


def _classify(markers: tuple[str, ...]) -> str:
    """What kind of run this is, from the artifacts it actually holds.

    An evolve run also carries a ``discovery/`` directory, so the tree is what
    decides: ``run_summary.json`` / ``tree.json`` come first. A directory holding
    only ``fe.db`` is a database run -- it has no tree to draw, and the tree
    endpoint must say that instead of inventing one.
    """
    if "run_summary.json" in markers or "tree.json" in markers:
        return TYPE_EVOLVE
    if "hpo" in markers:
        return TYPE_AUTOTUNE
    if "discovery" in markers:
        return TYPE_DISCOVERY
    if "fe.db" in markers:
        return TYPE_DATABASE
    return TYPE_UNKNOWN


def _depth_limit(settings: WebSettings) -> int:
    return max(1, int(settings.discovery_max_depth))


def _fixture_roots(settings: WebSettings) -> list[Path]:
    resolved: list[Path] = []
    for root in settings.fixture_roots:
        try:
            resolved.append(Path(root).resolve())
        except OSError:
            continue
    return resolved


def _registry_run_ids(settings: WebSettings) -> set[str]:
    """Run ids this service started -- the evidence that a run is real."""
    from faultevolve.webapi import run_registry

    if not run_registry.registry_configured(settings):
        return set()
    try:
        return {record.run_id for record in run_registry.list_records(settings)}
    except Exception:  # a broken registry must not blank the list
        return set()


def scan(settings: WebSettings) -> ScanOutcome:
    """Walk every configured root and return the runs found, with their origins.

    Duplicates (the same run id in two directories) keep both entries and get
    distinct ``external_id`` values; nothing is overwritten.
    """
    outcome = ScanOutcome()
    limit = _depth_limit(settings)
    fixtures = _fixture_roots(settings)
    started = _registry_run_ids(settings)

    locations: list[RunLocation] = []
    for root in _roots(settings):
        for directory, relative, markers in _walk(root, limit, outcome, settings):
            name = directory.name
            if not _valid_run_name(name):
                continue
            locations.append(
                RunLocation(
                    run_id=name,
                    external_id=name,
                    source_root=root,
                    relative_path=relative,
                    artifacts_dir=directory,
                    db_dir=directory if "fe.db" in markers else None,
                    run_type=_classify(markers),
                    origin=_origin(directory, fixtures, name, started),
                    readable=True,
                    markers=markers,
                )
            )
    outcome.scanned = len(locations)

    merged = _pair_split_layouts(locations, outcome)
    _assign_external_ids(merged)
    outcome.locations = merged
    for location in merged:
        if location.origin == ORIGIN_FIXTURE:
            outcome.excluded_fixtures += 1
        elif location.origin == ORIGIN_UNVERIFIED:
            outcome.unverified += 1
    outcome.listed = sum(
        1 for location in merged if location.origin != ORIGIN_FIXTURE
    )
    return outcome


def _has_only(
    markers: tuple[str, ...], *, db: bool, reports: bool
) -> bool:
    """Whether ``markers`` holds exactly the db, the report half, or both.

    ``reports`` asks for at least one report marker; ``db`` for ``fe.db``. Used to
    tell a split layout (each half in its own root) from two complete copies.
    """
    has_db = "fe.db" in markers
    has_report = any(marker in REPORT_MARKERS for marker in markers)
    return has_db == db and has_report == reports


def _split_pair(
    group: list[RunLocation],
) -> RunLocation | None:
    """Merge one complementary pair of halves, or ``None`` when it is not a pair.

    The condition is deliberately narrow: the same run id at the same relative
    path under two different roots, one holding *only* ``fe.db`` and the other
    holding report files but *no* ``fe.db``. Two complete copies of a run id stay
    two locations -- merging them would silently pick one run's numbers.
    """
    if len(group) != 2 or group[0].source_root == group[1].source_root:
        return None
    db_half = None
    report_half = None
    for candidate in group:
        if _has_only(candidate.markers, db=True, reports=False):
            db_half = candidate
        elif _has_only(candidate.markers, db=False, reports=True):
            report_half = candidate
    if db_half is None or report_half is None:
        return None
    markers = tuple(
        marker
        for marker in RUN_MARKERS
        if marker in set(db_half.markers) | set(report_half.markers)
    )
    return RunLocation(
        run_id=db_half.run_id,
        external_id=db_half.run_id,
        source_root=report_half.source_root,
        relative_path=report_half.relative_path,
        artifacts_dir=report_half.artifacts_dir,
        db_dir=db_half.db_dir,
        run_type=_classify(markers),
        origin=_best_origin(db_half.origin, report_half.origin),
        readable=True,
        markers=markers,
    )


def _pair_split_layouts(
    locations: list[RunLocation], outcome: ScanOutcome
) -> list[RunLocation]:
    """Join a database-only directory with its report-only twin (TODO D6.1).

    ``fe evolve --runs-dir A --artifacts-dir B`` writes ``A/<id>/fe.db`` and
    ``B/<id>/{run_summary.json,tree.json,...}``. Each half on its own is a real
    finding, and showing both as separate runs would give the UI a database row
    with no tree and a report row with no database. They are the same run, so they
    become one location with two homes.
    """
    grouped: dict[tuple[str, str], list[RunLocation]] = {}
    order: list[tuple[str, str]] = []
    for location in locations:
        key = (location.run_id, location.relative_path)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(location)

    merged: list[RunLocation] = []
    for key in order:
        pair = _split_pair(grouped[key])
        if pair is None:
            merged.extend(grouped[key])
            continue
        merged.append(pair)
        outcome.paired += 1
    return merged


def _best_origin(*origins: str) -> str:
    """The strongest evidence of two halves of one run.

    A database this service started, sitting next to artifacts inside a fixture
    root, is still a fixture -- so ``fixture`` outranks ``real``.
    """
    if ORIGIN_FIXTURE in origins:
        return ORIGIN_FIXTURE
    if ORIGIN_REAL in origins:
        return ORIGIN_REAL
    return ORIGIN_UNVERIFIED


def _assign_external_ids(locations: list[RunLocation]) -> None:
    """Rewrite the ids of a colliding run id, keeping each one reachable.

    The first occurrence in scan order keeps the bare run id so an existing
    bookmark or link to ``/api/runs/<id>`` keeps working; the others get a digest
    suffix. That is the "cannot silently overwrite" rule of TODO D6.2.
    """
    grouped: dict[str, list[RunLocation]] = {}
    for location in locations:
        grouped.setdefault(location.run_id, []).append(location)
    for run_id, group in grouped.items():
        if len(group) < 2:
            continue
        for index, location in enumerate(group):
            external = (
                run_id if index == 0 else _external_id(run_id, location.relative_path)
            )
            object.__setattr__(location, "external_id", external)


def _roots(settings: WebSettings) -> list[Path]:
    from faultevolve.webapi.paths import run_roots

    return run_roots(settings)


def _walk(
    root: Path, limit: int, outcome: ScanOutcome, settings: WebSettings
) -> list[tuple[Path, str, tuple[str, ...]]]:
    """Breadth-limited walk that never follows a symlink and never raises."""
    found: list[tuple[Path, str, tuple[str, ...]]] = []
    queue: list[tuple[Path, str, int]] = [(root, "", 0)]
    visits = 0
    while queue:
        directory, relative, depth = queue.pop(0)
        visits += 1
        if visits > MAX_VISITS:
            _record_error(outcome, relative or ".", "scan stopped at the visit ceiling")
            break
        try:
            children = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            _record_error(outcome, relative or ".", _reason(exc))
            continue
        for child in children:
            child_relative = f"{relative}/{child.name}" if relative else child.name
            try:
                is_link = child.is_symlink()
                is_dir = child.is_dir()
            except OSError as exc:
                _record_error(outcome, child_relative, _reason(exc))
                continue
            if is_link:
                # A link is recorded, not descended: a NAS volume full of symlinks
                # to itself would otherwise never finish.
                _record_error(outcome, child_relative, "symbolic link skipped")
                continue
            if not is_dir:
                continue
            if not settings.is_allowed(child):
                _record_error(outcome, child_relative, "outside the allowed roots")
                continue
            markers = _markers(child)
            if markers:
                found.append((child, child_relative, markers))
            if depth + 1 < limit:
                queue.append((child, child_relative, depth + 1))
    return found


def _record_error(outcome: ScanOutcome, relative_path: str, reason: str) -> None:
    """Append one scan error, stopping at the cap and saying that it stopped."""
    if len(outcome.errors) >= MAX_ERRORS:
        outcome.errors_truncated = True
        return
    outcome.errors.append(ScanError(relative_path, reason))


def _reason(exc: OSError) -> str:
    """An OSError mapped to something short that cannot leak more than a reason."""
    text = str(exc).lower()
    if "permission" in text or "denied" in text:
        return "permission denied"
    if "too many" in text:
        return "path too long"
    return type(exc).__name__


def _valid_run_name(name: str) -> bool:
    from faultevolve.webapi.paths import is_valid_id

    return is_valid_id(name)


def _origin(
    directory: Path, fixtures: list[Path], run_id: str, started: set[str]
) -> str:
    """Fixture / real / unverified, from evidence the server holds.

    A name that merely *looks* like a fixture is not evidence -- TODO D6.2 forbids
    judging authenticity by name. Only an explicitly configured fixture root (or a
    run this service started) settles the question.
    """
    resolved = directory
    for root in fixtures:
        if resolved == root or root in resolved.parents:
            return ORIGIN_FIXTURE
    if run_id in started:
        return ORIGIN_REAL
    return ORIGIN_UNVERIFIED


def listed_locations(settings: WebSettings) -> list[RunLocation]:
    """Runs a product listing may show: everything found except fixtures."""
    return [
        location
        for location in scan(settings).locations
        if location.origin != ORIGIN_FIXTURE
    ]


def find(settings: WebSettings, key: str) -> RunLocation | None:
    """Look one run up by external id, falling back to a unique run id.

    Fixtures are searchable even though they are not listed: a bookmarked demo
    link keeps working, while the product listing stays clean.
    """
    from faultevolve.webapi.paths import validate_id

    validate_id(key, kind="run_id", field="run_id")
    outcome = scan(settings)
    match = outcome.by_external_id().get(key)
    if match is not None:
        return match
    group = outcome.by_run_id().get(key, [])
    if len(group) == 1:
        return group[0]
    return None
